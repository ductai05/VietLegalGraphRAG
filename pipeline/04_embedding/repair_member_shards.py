"""Deduplicate member outputs and encode only chunks missing from the combined runs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from embedding_common import atomic_write_json, read_json
from member_shards_utils import (
    CONFIG_KEYS,
    _compare_config,
    _load_manifests,
    discover_member_roots,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-root", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--num-members", type=int, default=5)
    parser.add_argument("--batch-size", default="128")
    parser.add_argument("--token-budget", default="49152")
    parser.add_argument("--max-length", default="1024")
    parser.add_argument("--attn-implementation", default="sdpa")
    parser.add_argument("--cache-dir", default="/tmp/vnlegal_hf_cache")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--allow-cpu", action="store_true")
    return parser.parse_args()


def resolve_device(requested: str, allow_cpu: bool) -> str:
    import torch

    if requested.startswith("cuda") and not torch.cuda.is_available():
        if allow_cpu:
            print("WARNING: CUDA is unavailable; encoding missing chunks on CPU.")
            return "cpu"
        raise RuntimeError(
            "CUDA is unavailable, but repairing missing chunks requires embedding inference. "
            "In Kaggle, open Notebook options, set Accelerator to GPU, restart the session, "
            "then rerun KAGGLE_MERGE.py. To explicitly accept slow CPU inference, set "
            "ALLOW_CPU_REPAIR=True in KAGGLE_MERGE.py."
        )
    return requested


def link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def write_missing_payload(
    canonical_payload: Path, missing_ids: set[str], output_path: Path
) -> int:
    if output_path.exists():
        existing_ids = {
            chunk_id
            for batch in pq.ParquetFile(output_path).iter_batches(
                batch_size=100_000, columns=["chunk_id"]
            )
            for chunk_id in batch.column(0).to_pylist()
        }
        if existing_ids != missing_ids:
            raise ValueError(f"Existing missing payload is stale: {output_path}")
        return len(existing_ids)
    value_set = pa.array(sorted(missing_ids))
    writer: pq.ParquetWriter | None = None
    written = 0
    try:
        for batch in pq.ParquetFile(canonical_payload).iter_batches(batch_size=100_000):
            mask = pc.is_in(batch.column(batch.schema.get_field_index("chunk_id")), value_set=value_set)
            selected = pa.Table.from_batches([batch]).filter(mask)
            if selected.num_rows == 0:
                continue
            if writer is None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                writer = pq.ParquetWriter(output_path, selected.schema, compression="zstd")
            writer.write_table(selected)
            written += selected.num_rows
    finally:
        if writer is not None:
            writer.close()
    if written != len(missing_ids):
        raise ValueError(f"Missing payload extraction wrote {written:,}/{len(missing_ids):,} rows")
    return written


def main() -> None:
    args = parse_args()
    completed_manifest = read_json(args.output_dir / "manifest.json")
    if completed_manifest.get("repair") and completed_manifest.get("completed_rows"):
        print(
            f"Repair already complete: {completed_manifest['completed_rows']:,} rows "
            f"in {args.output_dir}"
        )
        return
    device = resolve_device(args.device, args.allow_cpu)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    member_roots = discover_member_roots(args.search_root, args.num_members)
    canonical_payload = member_roots[1].parent / "embed_payload_v0.1.parquet"
    if not canonical_payload.exists():
        raise FileNotFoundError(f"Member 1 full payload is missing: {canonical_payload}")

    canonical_file = pq.ParquetFile(canonical_payload)
    canonical_rows = canonical_file.metadata.num_rows
    canonical_ids = {
        chunk_id
        for batch in canonical_file.iter_batches(batch_size=100_000, columns=["chunk_id"])
        for chunk_id in batch.column(0).to_pylist()
    }
    if len(canonical_ids) != canonical_rows:
        raise ValueError(f"Canonical payload contains duplicate chunk IDs: {canonical_payload}")
    manifests = _load_manifests(member_roots)
    reference = manifests[1][0][1]
    config = {key: reference.get(key) for key in CONFIG_KEYS}
    merged_shards: dict[str, Any] = {}
    seen_ids: set[str] = set()
    duplicate_rows = 0

    for member_id, entries in sorted(manifests.items()):
        for gpu_dir, manifest in entries:
            _compare_config(config, manifest, str(gpu_dir))
            for key, info in sorted(manifest["shards"].items()):
                payload_path = gpu_dir / info["payload"]
                vector_path = gpu_dir / info["vectors"]
                table = pq.read_table(payload_path)
                vectors = np.load(vector_path, mmap_mode="r")
                chunk_ids = table.column("chunk_id").to_pylist()
                if len(chunk_ids) != len(vectors):
                    raise ValueError(f"Payload/vector row mismatch in {gpu_dir}, shard {key}")

                keep = np.zeros(len(chunk_ids), dtype=np.bool_)
                for index, chunk_id in enumerate(chunk_ids):
                    if chunk_id not in seen_ids:
                        keep[index] = True
                        seen_ids.add(chunk_id)
                duplicate_rows += int((~keep).sum())
                if not keep.any():
                    continue

                output_key = f"existing_{key}"
                output_vectors = args.output_dir / f"vectors_{output_key}.npy"
                output_payload = args.output_dir / f"payload_{output_key}.parquet"
                if output_vectors.exists() != output_payload.exists():
                    raise FileExistsError(
                        f"Incomplete repair shard; remove both files and rerun: "
                        f"{output_vectors}, {output_payload}"
                    )
                if not output_vectors.exists():
                    if keep.all():
                        link_or_copy(vector_path, output_vectors)
                        link_or_copy(payload_path, output_payload)
                    else:
                        with output_vectors.open("wb") as handle:
                            np.save(handle, np.asarray(vectors)[keep])
                        pq.write_table(
                            table.filter(pa.array(keep)), output_payload, compression="zstd"
                        )

                kept_ids = [chunk_id for chunk_id, should_keep in zip(chunk_ids, keep, strict=True) if should_keep]
                merged_shards[output_key] = {
                    "status": "done",
                    "rows": len(kept_ids),
                    "first_chunk_id": kept_ids[0],
                    "last_chunk_id": kept_ids[-1],
                    "vectors": output_vectors.name,
                    "payload": output_payload.name,
                    "source_member": member_id,
                }

    unexpected_ids = seen_ids - canonical_ids
    if unexpected_ids:
        raise ValueError(f"Existing outputs contain unexpected chunk IDs: {sorted(unexpected_ids)[:5]}")
    missing_ids = canonical_ids - seen_ids
    print(
        f"Existing outputs: unique={len(seen_ids):,} duplicates_removed={duplicate_rows:,} "
        f"missing_to_encode={len(missing_ids):,}"
    )
    if missing_ids:
        print(
            f"Encoding missing chunks now: {len(missing_ids):,} "
            f"out of {len(canonical_ids):,} canonical chunks"
        )

    if missing_ids:
        missing_payload = args.work_dir / "missing_payload.parquet"
        repair_output = args.work_dir / "missing_encoded"
        write_missing_payload(canonical_payload, missing_ids, missing_payload)
        subprocess.run(
            [
                "python",
                "embed_shards.py",
                "--payload",
                str(missing_payload),
                "--output-dir",
                str(repair_output),
                "--batch-size",
                args.batch_size,
                "--token-budget",
                args.token_budget,
                "--max-length",
                args.max_length,
                "--attn-implementation",
                args.attn_implementation,
                "--cache-dir",
                args.cache_dir,
                "--device",
                device,
            ],
            check=True,
        )
        repair_manifest = json.loads(
            (repair_output / "manifest.json").read_text(encoding="utf-8")
        )
        _compare_config(config, repair_manifest, str(repair_output))
        for key, info in sorted(repair_manifest["shards"].items()):
            output_key = f"repair_{key}"
            output_vectors = args.output_dir / f"vectors_{output_key}.npy"
            output_payload = args.output_dir / f"payload_{output_key}.parquet"
            link_or_copy(repair_output / info["vectors"], output_vectors)
            link_or_copy(repair_output / info["payload"], output_payload)
            merged_shards[output_key] = {
                **info,
                "vectors": output_vectors.name,
                "payload": output_payload.name,
            }

    completed_rows = sum(item["rows"] for item in merged_shards.values())
    if completed_rows != len(canonical_ids):
        raise ValueError(f"Repair output has {completed_rows:,}/{len(canonical_ids):,} rows")
    manifest = dict(config)
    manifest["shards"] = dict(sorted(merged_shards.items()))
    manifest["completed_rows"] = completed_rows
    manifest["repair"] = {
        "duplicates_removed": duplicate_rows,
        "missing_encoded": len(missing_ids),
        "canonical_payload": str(canonical_payload),
    }
    atomic_write_json(args.output_dir / "manifest.json", manifest)
    print(f"Repair complete: {completed_rows:,} unique rows in {args.output_dir}")


if __name__ == "__main__":
    main()
