"""Upload embedding shards to Qdrant using TurboQuant (BITS4) with on-disk optimizations and resumption support."""

from __future__ import annotations

import argparse
import logging
import json
import shutil
import sys
import time
from pathlib import Path
import numpy as np
import polars as pl
from qdrant_client import QdrantClient, models

sys.path.append(str(Path(__file__).resolve().parent))
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
    parser.add_argument("--url", required=True, help="Qdrant server URL (e.g., http://localhost:6333)")
    parser.add_argument("--api-key", default=None, help="API Key for Qdrant Server if authenticated")
    parser.add_argument("--collection", default=COLLECTION_NAME)
    parser.add_argument("--upsert-batch", type=int, default=200)
    parser.add_argument("--include-text", action="store_true")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument(
        "--final-index",
        choices=["hnsw", "scan", "auto"],
        default="auto",
        help="Finalization indexing strategy: build HNSW, keep full scan (m=0), or auto (build HNSW only if >= 3GB free disk).",
    )
    return parser.parse_args()


def safe_upsert(client: QdrantClient, collection: str, points: list[models.PointStruct], max_retries: int = 8) -> None:
    backoff = 3
    for attempt in range(1, max_retries + 1):
        try:
            client.upsert(collection, points=points, wait=True)
            return
        except Exception as exc:
            logging.warning(
                "Upsert failed on attempt %d/%d: %s. Retrying in %d seconds...",
                attempt, max_retries, exc, backoff
            )
            if attempt == max_retries:
                raise
            time.sleep(backoff)
            backoff *= 2


def ensure_collection(client: QdrantClient, name: str, recreate: bool) -> None:
    exists = client.collection_exists(name)
    if exists and recreate:
        client.delete_collection(name)
        exists = False
    if exists:
        return

    # TurboQuantization Config (BITS4, on-disk)
    quantization_config = models.TurboQuantization(
        turbo=models.TurboQuantQuantizationConfig(
            bits=models.TurboQuantBitSize.BITS4,
            always_ram=False,  # Loaded from disk using memory map
        )
    )

    # Disable indexing during upload (m=0, indexing_threshold=0)
    hnsw_config = models.HnswConfigDiff(m=0)
    optimizers_config = models.OptimizersConfigDiff(
        indexing_threshold=0,
        default_segment_number=2,
    )

    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(
            size=VECTOR_SIZE,
            distance=models.Distance.COSINE,
            on_disk=True,  # Store raw float16 vectors on disk
        ),
        hnsw_config=hnsw_config,
        optimizers_config=optimizers_config,
        quantization_config=quantization_config,
    )

    for field, schema in INDEX_FIELDS.items():
        client.create_payload_index(name, field_name=field, field_schema=schema)


def finalize_collection(client: QdrantClient, name: str, strategy: str) -> None:
    free_gb = shutil.disk_usage(".").free / (1024**3)
    logging.info("Checking disk space for finalization: %.2f GB free.", free_gb)

    should_build_hnsw = False
    if strategy == "hnsw":
        should_build_hnsw = True
    elif strategy == "scan":
        should_build_hnsw = False
    elif strategy == "auto":
        if free_gb >= 3.0:
            should_build_hnsw = True
            logging.info("Free disk space (%.2f GB) >= 3.0 GB. Building HNSW index.", free_gb)
        else:
            logging.warning("Free disk space (%.2f GB) < 3.0 GB. Keeping exact scan (m=0) to protect disk.", free_gb)

    if should_build_hnsw:
        logging.info("Finalizing collection: building HNSW index on-disk (m=6, ef_construct=64)...")
        client.update_collection(
            collection_name=name,
            hnsw_config=models.HnswConfigDiff(
                m=6,
                ef_construct=64,
                on_disk=True,
            ),
            optimizers_config=models.OptimizersConfigDiff(
                indexing_threshold=20000,
            ),
        )
        logging.info("Finalization completed.")
    else:
        logging.info("Finalizing collection: Keeping exact search scan (m=0) strategy.")


def main() -> None:
    args = parse_args()

    source_manifest_path = args.shards_dir / "manifest.json"
    source_manifest = read_json(source_manifest_path)
    if not source_manifest:
        raise FileNotFoundError(
            f"Missing {source_manifest_path}. Run embed_shards.py successfully before uploading."
        )

    setup_logging(args.shards_dir / "qdrant_build_turbo.log")
    build_manifest_path = args.shards_dir / "qdrant_manifest_turbo.json"
    build_manifest = read_json(build_manifest_path, {"shards": {}})

    if args.recreate:
        build_manifest = {"shards": {}}

    completed = [
        (key, value)
        for key, value in sorted(source_manifest["shards"].items())
        if value.get("status") == "done"
    ]

    client = QdrantClient(url=args.url, api_key=args.api_key, timeout=300)

    try:
        ensure_collection(client, args.collection, args.recreate)

        for shard_idx, (shard_key, shard_info) in enumerate(completed):
            previous = build_manifest["shards"].get(shard_key, {})
            if (
                previous.get("status") == "done"
                and previous.get("rows") == shard_info["rows"]
            ):
                logging.info("Skipping upserted shard %s", shard_key)
                continue

            payload_path = args.shards_dir / shard_info["payload"]
            vector_path = args.shards_dir / shard_info["vectors"]
            payload_df = pl.read_parquet(payload_path, glob=False)
            vectors = np.load(vector_path, mmap_mode="r")

            if len(vectors) != payload_df.height:
                raise ValueError(f"Payload/vector row mismatch in shard {shard_key}")

            rows = payload_df.to_dicts()
            logging.info("Uploading shard %s (%d rows)...", shard_key, payload_df.height)

            for indices in batched(range(payload_df.height), args.upsert_batch):
                points = [
                    models.PointStruct(
                        id=stable_point_id(rows[index]["chunk_id"]),
                        vector=vectors[index].astype(np.float32).tolist(),
                        payload=row_to_payload(rows[index], include_text=args.include_text),
                    )
                    for index in indices
                ]
                safe_upsert(client, args.collection, points=points)

            build_manifest["shards"][shard_key] = {
                "status": "done",
                "rows": payload_df.height,
            }
            build_manifest["collection"] = args.collection
            build_manifest["point_count"] = client.count(args.collection, exact=True).count
            atomic_write_json(build_manifest_path, build_manifest)
            logging.info("Successfully uploaded shard %s", shard_key)

        # Run finalization to build index or keep scan
        finalize_collection(client, args.collection, args.final_index)

    finally:
        client.close()


if __name__ == "__main__":
    main()
