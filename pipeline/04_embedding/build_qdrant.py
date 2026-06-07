"""Create a Qdrant collection and upsert completed embedding shards."""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import numpy as np
import polars as pl
from qdrant_client import QdrantClient, models

from embedding_common import (
    COLLECTION_NAME,
    VECTOR_SIZE,
    atomic_write_json,
    batched,
    read_json,
    row_to_payload,
    setup_logging,
    stable_point_id,
)

INDEX_FIELDS = {
    "doc_id": models.PayloadSchemaType.INTEGER,
    "chunk_type": models.PayloadSchemaType.KEYWORD,
    "legal_type": models.PayloadSchemaType.KEYWORD,
    "issuing_authority": models.PayloadSchemaType.KEYWORD,
    "effect_status": models.PayloadSchemaType.KEYWORD,
    "linh_vuc": models.PayloadSchemaType.KEYWORD,
    "nganh": models.PayloadSchemaType.KEYWORD,
    "issuance_date_ts": models.PayloadSchemaType.INTEGER,
    "effect_date_ts": models.PayloadSchemaType.INTEGER,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards-dir", type=Path, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--storage-dir", type=Path)
    target.add_argument("--url", help="Qdrant server URL, for example http://localhost:6333.")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--collection", default=COLLECTION_NAME)
    parser.add_argument("--upsert-batch", type=int, default=200)
    parser.add_argument("--include-text", action="store_true")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--archive", type=Path, default=None)
    return parser.parse_args()


def ensure_collection(client: QdrantClient, name: str, recreate: bool) -> None:
    exists = client.collection_exists(name)
    if exists and recreate:
        client.delete_collection(name)
        exists = False
    if exists:
        return
    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
        hnsw_config=models.HnswConfigDiff(
            m=16,
            ef_construct=100,
            full_scan_threshold=10_000,
        ),
        optimizers_config=models.OptimizersConfigDiff(default_segment_number=4),
    )
    for field, schema in INDEX_FIELDS.items():
        client.create_payload_index(name, field_name=field, field_schema=schema)


def main() -> None:
    args = parse_args()
    if args.storage_dir:
        args.storage_dir.mkdir(parents=True, exist_ok=True)
    if args.archive is not None and args.storage_dir is None:
        raise ValueError("--archive is only supported with --storage-dir")
    setup_logging(args.shards_dir / "qdrant_build.log")
    source_manifest = read_json(args.shards_dir / "manifest.json")
    if not source_manifest:
        raise FileNotFoundError(f"Missing {args.shards_dir / 'manifest.json'}")
    build_manifest_path = args.shards_dir / "qdrant_manifest.json"
    build_manifest = read_json(build_manifest_path, {"shards": {}})
    if build_manifest.get("shards") and not args.recreate:
        if build_manifest.get("collection") not in (None, args.collection):
            raise ValueError("Build manifest belongs to a different collection")
        if build_manifest.get("include_text", False) != args.include_text:
            raise ValueError("Changing --include-text requires --recreate")
    client = (
        QdrantClient(path=str(args.storage_dir))
        if args.storage_dir
        else QdrantClient(url=args.url, api_key=args.api_key)
    )
    ensure_collection(client, args.collection, args.recreate)
    if args.recreate:
        build_manifest = {"shards": {}}

    completed = [
        (key, value)
        for key, value in sorted(source_manifest["shards"].items())
        if value.get("status") == "done"
    ]
    for shard_key, shard_info in completed:
        previous = build_manifest["shards"].get(shard_key, {})
        if (
            previous.get("status") == "done"
            and previous.get("rows") == shard_info["rows"]
        ):
            logging.info("Skipping upserted shard %s", shard_key)
            continue
        payload_path = args.shards_dir / shard_info["payload"]
        vector_path = args.shards_dir / shard_info["vectors"]
        payload_df = pl.read_parquet(payload_path)
        if args.include_text and "chunk_text" not in payload_df.columns:
            raise ValueError(
                "--include-text requires shards created with --include-text-in-payload"
            )
        vectors = np.load(vector_path, mmap_mode="r")
        if len(vectors) != payload_df.height:
            raise ValueError(f"Payload/vector row mismatch in shard {shard_key}")

        rows = payload_df.to_dicts()
        for indices in batched(range(payload_df.height), args.upsert_batch):
            points = [
                models.PointStruct(
                    id=stable_point_id(rows[index]["chunk_id"]),
                    vector=vectors[index].astype(np.float32).tolist(),
                    payload=row_to_payload(rows[index], include_text=args.include_text),
                )
                for index in indices
            ]
            client.upsert(args.collection, points=points, wait=True)

        build_manifest["shards"][shard_key] = {
            "status": "done",
            "rows": payload_df.height,
        }
        build_manifest["collection"] = args.collection
        build_manifest["include_text"] = args.include_text
        build_manifest["point_count"] = client.count(args.collection, exact=True).count
        atomic_write_json(build_manifest_path, build_manifest)
        logging.info("Upserted shard %s", shard_key)

    expected = sum(item["rows"] for _, item in completed)
    actual = client.count(args.collection, exact=True).count
    if actual != expected:
        raise ValueError(f"Qdrant count mismatch: expected {expected:,}, got {actual:,}")
    logging.info("Qdrant collection contains %s points", f"{actual:,}")
    client.close()

    if args.archive is not None and args.storage_dir is not None:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        archive_base = args.archive.with_suffix("")
        result = shutil.make_archive(str(archive_base), "zip", args.storage_dir)
        logging.info("Created archive %s", result)


if __name__ == "__main__":
    main()
