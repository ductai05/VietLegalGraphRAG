"""Build compact FAISS IVF-PQ indexes directly from read-only member shards."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from embedding_common import VECTOR_SIZE, atomic_write_json, read_json
from member_shards_utils import discover_member_roots


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search-root", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repair-dir", type=Path, default=None)
    parser.add_argument("--num-members", type=int, default=5)
    parser.add_argument("--factory", default="IVF4096,PQ64x8")
    parser.add_argument("--train-size", type=int, default=200_000)
    parser.add_argument("--add-batch-size", type=int, default=20_000)
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args()


def source_shards(
    search_roots: list[Path], num_members: int, repair_dir: Path | None
) -> list[tuple[str, list[tuple[Path, dict[str, Any]]]]]:
    member_roots = discover_member_roots(search_roots, num_members)
    sources: list[tuple[str, list[tuple[Path, dict[str, Any]]]]] = []
    for member_id, member_root in sorted(member_roots.items()):
        entries = []
        for gpu_dir in (member_root / "gpu0", member_root / "gpu1"):
            manifest = read_json(gpu_dir / "manifest.json")
            if manifest.get("shards"):
                entries.append((gpu_dir, manifest))
        if entries:
            sources.append((f"member_{member_id}", entries))
    if repair_dir is not None:
        repair_manifest = read_json(repair_dir / "manifest.json")
        if repair_manifest.get("shards"):
            sources.append(("repair", [(repair_dir, repair_manifest)]))
    return sources


def iter_shards(
    entries: list[tuple[Path, dict[str, Any]]],
) -> Iterator[tuple[Path, Path, int]]:
    for shard_dir, manifest in entries:
        for _, info in sorted(manifest["shards"].items()):
            if info.get("status") != "done":
                continue
            yield shard_dir / info["vectors"], shard_dir / info["payload"], int(info["rows"])


def training_sample(
    shards: list[tuple[Path, Path, int]], train_size: int
) -> np.ndarray:
    total_rows = sum(rows for _, _, rows in shards)
    target = min(train_size, total_rows)
    samples: list[np.ndarray] = []
    remaining_target = target
    remaining_rows = total_rows
    for vector_path, _, rows in shards:
        take = min(rows, max(1, round(remaining_target * rows / remaining_rows)))
        vectors = np.load(vector_path, mmap_mode="r")
        indices = np.linspace(0, rows - 1, num=take, dtype=np.int64)
        samples.append(np.asarray(vectors[indices], dtype=np.float32))
        remaining_target -= take
        remaining_rows -= rows
    return np.concatenate(samples, axis=0)[:target]


def write_source_index(
    name: str,
    entries: list[tuple[Path, dict[str, Any]]],
    output_dir: Path,
    trained_index: Any,
    add_batch_size: int,
) -> dict[str, Any]:
    import faiss

    shards = list(iter_shards(entries))
    expected_rows = sum(rows for _, _, rows in shards)
    if not shards:
        raise ValueError(f"No completed shards found for {name}")

    index_path = output_dir / f"{name}.faiss"
    payload_path = output_dir / f"{name}.payload.arrow"
    index_tmp = index_path.with_suffix(".faiss.tmp")
    payload_tmp = payload_path.with_suffix(".arrow.tmp")
    for path in (index_tmp, payload_tmp):
        if path.exists():
            path.unlink()

    print(f"Building {name}: rows={expected_rows:,}")
    index = faiss.clone_index(trained_index)

    payload_sink = pa.OSFile(str(payload_tmp), "wb")
    payload_writer: ipc.RecordBatchFileWriter | None = None
    payload_schema: pa.Schema | None = None
    added = 0
    try:
        for vector_path, shard_payload_path, rows in shards:
            vectors = np.load(vector_path, mmap_mode="r")
            payload = pq.read_table(shard_payload_path)
            if len(vectors) != rows or payload.num_rows != rows:
                raise ValueError(f"Row mismatch in {vector_path} / {shard_payload_path}")
            if payload_writer is None:
                payload_schema = payload.schema
                payload_writer = ipc.new_file(
                    payload_sink,
                    payload.schema,
                    options=ipc.IpcWriteOptions(compression="zstd"),
                )
            elif payload.schema != payload_schema:
                payload = payload.cast(payload_schema)
            payload_writer.write_table(payload)
            for start in range(0, rows, add_batch_size):
                stop = min(start + add_batch_size, rows)
                index.add(np.asarray(vectors[start:stop], dtype=np.float32))
            added += rows
            print(f"  {name}: indexed {added:,}/{expected_rows:,}")
    finally:
        if payload_writer is not None:
            payload_writer.close()
        payload_sink.close()

    if index.ntotal != expected_rows:
        raise ValueError(f"{name} index has {index.ntotal:,}/{expected_rows:,} vectors")
    faiss.write_index(index, str(index_tmp))
    os.replace(index_tmp, index_path)
    os.replace(payload_tmp, payload_path)
    return {
        "status": "done",
        "rows": expected_rows,
        "index": index_path.name,
        "payload": payload_path.name,
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "manifest.json"
    manifest = read_json(manifest_path, {"format": "faiss_members_v1", "indexes": {}})
    if manifest.get("factory") not in (None, args.factory) and not args.recreate:
        raise ValueError("Existing FAISS output uses a different factory; pass --recreate")
    if args.recreate:
        manifest = {"format": "faiss_members_v1", "indexes": {}}
    manifest["factory"] = args.factory

    sources = source_shards(args.search_root, args.num_members, args.repair_dir)
    trained_path = args.output_dir / "trained.faiss"
    if trained_path.exists() and not args.recreate:
        import faiss

        trained_index = faiss.read_index(str(trained_path))
    else:
        import faiss

        all_shards = [
            shard
            for _, entries in sources
            for shard in iter_shards(entries)
        ]
        print(f"Training shared FAISS codebook: factory={args.factory}")
        sample = training_sample(all_shards, args.train_size)
        trained_index = faiss.index_factory(
            VECTOR_SIZE, args.factory, faiss.METRIC_INNER_PRODUCT
        )
        trained_index.train(sample)
        del sample
        faiss.write_index(trained_index, str(trained_path))

    for name, entries in sources:
        existing = manifest["indexes"].get(name)
        if existing and existing.get("status") == "done" and not args.recreate:
            print(f"Skipping completed index: {name}")
            continue
        manifest["indexes"][name] = write_source_index(
            name,
            entries,
            args.output_dir,
            trained_index,
            args.add_batch_size,
        )
        manifest["completed_rows"] = sum(
            item["rows"] for item in manifest["indexes"].values() if item.get("status") == "done"
        )
        atomic_write_json(manifest_path, manifest)

    print(
        f"FAISS member indexes complete: {manifest['completed_rows']:,} rows "
        f"in {args.output_dir}"
    )


if __name__ == "__main__":
    main()
