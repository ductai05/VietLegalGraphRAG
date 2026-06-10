"""Validate read-only member datasets and encode only missing unique chunk IDs."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from embedding_common import atomic_write_json, read_json
from member_shards_utils import (
    CONFIG_KEYS,
    _compare_config,
    discover_member_roots,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-root", type=Path, action="append", required=True)
    parser.add_argument("--canonical-payload", type=Path, default=None)
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
            "CUDA is unavailable, but missing chunks require embedding inference. "
            "Enable a Kaggle GPU or pass --allow-cpu."
        )
    return requested


def write_missing_payload(
    canonical_payload: Path, missing_ids: set[str], output_path: Path
) -> int:
    value_set = pa.array(sorted(missing_ids))
    writer: pq.ParquetWriter | None = None
    written = 0
    try:
        for batch in pq.ParquetFile(canonical_payload).iter_batches(batch_size=100_000):
            chunk_id = batch.column(batch.schema.get_field_index("chunk_id"))
            selected = pa.Table.from_batches([batch]).filter(
                pc.is_in(chunk_id, value_set=value_set)
            )
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
        raise ValueError(f"Missing payload wrote {written:,}/{len(missing_ids):,} rows")
    return written


def scan_member_ids(
    member_roots: dict[int, Path],
) -> tuple[set[str], int, dict[str, Any]]:
    manifests: dict[int, list[tuple[Path, dict[str, Any]]]] = {}
    for member_id, member_root in sorted(member_roots.items()):
        manifests[member_id] = []
        for gpu_dir in (member_root / "gpu0", member_root / "gpu1"):
            manifest = read_json(gpu_dir / "manifest.json")
            if manifest.get("shards"):
                manifests[member_id].append((gpu_dir, manifest))
    available = [entry for entries in manifests.values() for entry in entries]
    if not available:
        raise ValueError("No completed member manifests were found")
    reference = available[0][1]
    config = {key: reference.get(key) for key in CONFIG_KEYS}
    seen_ids: set[str] = set()
    duplicate_rows = 0
    for entries in manifests.values():
        for gpu_dir, manifest in entries:
            _compare_config(config, manifest, str(gpu_dir))
            for info in manifest["shards"].values():
                if info.get("status") != "done":
                    continue
                payload_path = gpu_dir / info["payload"]
                chunk_ids = (
                    pq.read_table(payload_path, columns=["chunk_id"])
                    .column("chunk_id")
                    .to_pylist()
                )
                for chunk_id in chunk_ids:
                    if chunk_id in seen_ids:
                        duplicate_rows += 1
                    else:
                        seen_ids.add(chunk_id)
    return seen_ids, duplicate_rows, config


def completed_output_ids(output_dir: Path) -> set[str]:
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        chunk_id
        for info in manifest.get("shards", {}).values()
        if info.get("status") == "done"
        for chunk_id in (
            pq.read_table(output_dir / info["payload"], columns=["chunk_id"])
            .column("chunk_id")
            .to_pylist()
        )
    }


def main() -> None:
    args = parse_args()
    member_roots = discover_member_roots(args.search_root, args.num_members)
    canonical_payload = args.canonical_payload or (
        member_roots[1].parent / "embed_payload_v0.1.parquet"
    )
    if not canonical_payload.exists():
        raise FileNotFoundError(f"Canonical payload is missing: {canonical_payload}")

    canonical_file = pq.ParquetFile(canonical_payload)
    canonical_ids = {
        chunk_id
        for batch in canonical_file.iter_batches(
            batch_size=100_000, columns=["chunk_id"]
        )
        for chunk_id in batch.column(0).to_pylist()
    }
    if len(canonical_ids) != canonical_file.metadata.num_rows:
        raise ValueError(f"Canonical payload contains duplicate chunk IDs: {canonical_payload}")
    seen_ids, duplicate_rows, config = scan_member_ids(member_roots)
    unexpected_ids = seen_ids - canonical_ids
    if unexpected_ids:
        raise ValueError(
            f"Member outputs contain unexpected chunk IDs: {sorted(unexpected_ids)[:5]}"
        )
    missing_ids = canonical_ids - seen_ids
    existing_repair_ids = completed_output_ids(args.output_dir)
    stale_repair_ids = existing_repair_ids - missing_ids
    if stale_repair_ids:
        raise ValueError(
            f"Existing repair output contains {len(stale_repair_ids):,} rows that are "
            f"no longer missing. Use a clean repair output directory. "
            f"Examples: {sorted(stale_repair_ids)[:5]}"
        )
    print(
        f"Member outputs: unique={len(seen_ids):,} "
        f"duplicates_to_ignore={duplicate_rows:,} "
        f"missing_to_encode={len(missing_ids):,}"
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        **config,
        "canonical_rows": len(canonical_ids),
        "member_rows": len(seen_ids),
        "member_duplicate_rows": duplicate_rows,
        "missing_encoded": len(missing_ids),
        "canonical_payload": str(canonical_payload),
    }
    if not missing_ids:
        atomic_write_json(args.output_dir / "repair_summary.json", summary)
        print("No missing chunks; no repair vector shards were written.")
        return

    device = resolve_device(args.device, args.allow_cpu)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    missing_payload = args.work_dir / "missing_payload.parquet"
    write_missing_payload(canonical_payload, missing_ids, missing_payload)
    subprocess.run(
        [
            "python",
            "embed_shards.py",
            "--payload",
            str(missing_payload),
            "--output-dir",
            str(args.output_dir),
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
    manifest_path = args.output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["repair"] = summary
    atomic_write_json(manifest_path, manifest)
    atomic_write_json(args.output_dir / "repair_summary.json", summary)
    print(f"Encoded {len(missing_ids):,} missing chunks into {args.output_dir}")


if __name__ == "__main__":
    main()
