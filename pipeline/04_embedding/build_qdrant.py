"""Create a Qdrant collection and upload embedding shards (supports local, cloud, and multi-cluster)."""

from __future__ import annotations

import argparse
import logging
import shutil
import json
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
    
    # Target choice: local, cloud, multi (default is local)
    parser.add_argument(
        "--target",
        choices=["local", "cloud", "multi"],
        default="local",
        help="Target deployment type: local storage directory, cloud instance, or partitioned multi-cluster upload.",
    )
    
    # Connection configurations
    parser.add_argument("--storage-dir", type=Path, help="Path to local Qdrant storage directory (required if target is local).")
    parser.add_argument("--url", help="Qdrant server URL, for example http://localhost:6333 (required if target is cloud).")
    parser.add_argument("--api-key", default=None, help="API Key for Qdrant Cloud or protected server.")
    parser.add_argument("--clusters-config", type=Path, help="Path to JSON configuration for multi-cluster upload (required if target is multi).")
    
    # Collection configurations
    parser.add_argument("--collection", default=COLLECTION_NAME)
    parser.add_argument("--upsert-batch", type=int, default=200)
    parser.add_argument("--include-text", action="store_true")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--archive", type=Path, default=None)
    
    # Compression/Quantization settings
    parser.add_argument(
        "--quantization",
        choices=["none", "scalar", "pq"],
        default="none",
        help="Quantization type for compression (none, scalar, pq). Cloud target defaults to pq if compression is needed.",
    )
    return parser.parse_args()


def ensure_collection(client: QdrantClient, name: str, recreate: bool, quantization: str = "none") -> None:
    exists = client.collection_exists(name)
    if exists and recreate:
        client.delete_collection(name)
        exists = False
    if exists:
        return

    # Configure Quantization
    quantization_config = None
    if quantization == "scalar":
        quantization_config = models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(
                type=models.ScalarType.INT8,
                quantile=0.99,
                always_ram=False,
            )
        )
    elif quantization == "pq":
        quantization_config = models.ProductQuantization(
            product=models.ProductQuantizationConfig(
                compression=models.CompressionRatio.X64,
                always_ram=False,
            )
        )

    # Apply optimizations: Set m=0 to disable indexing and opt for exact search on disk to save space
    hnsw_config = (
        models.HnswConfigDiff(m=0)
        if quantization != "none"
        else models.HnswConfigDiff(
            m=16,
            ef_construct=100,
            full_scan_threshold=10_000,
        )
    )
    optimizers_config = (
        models.OptimizersConfigDiff(default_segment_number=2, indexing_threshold=0)
        if quantization != "none"
        else models.OptimizersConfigDiff(default_segment_number=4)
    )

    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
        hnsw_config=hnsw_config,
        optimizers_config=optimizers_config,
        quantization_config=quantization_config,
    )
    for field, schema in INDEX_FIELDS.items():
        client.create_payload_index(name, field_name=field, field_schema=schema)


def main() -> None:
    args = parse_args()
    
    # Validate configurations
    if args.target == "local":
        if not args.storage_dir:
            raise ValueError("--storage-dir is required when target is local")
    elif args.target == "cloud":
        if not args.url:
            raise ValueError("--url is required when target is cloud")
    elif args.target == "multi":
        if not args.clusters_config:
            raise ValueError("--clusters-config is required when target is multi")
        if not args.clusters_config.exists():
            raise FileNotFoundError(f"Clusters config file not found: {args.clusters_config}")

    if args.archive is not None and args.target != "local":
        raise ValueError("--archive is only supported with local target")

    source_manifest_path = args.shards_dir / "manifest.json"
    source_manifest = read_json(source_manifest_path)
    if not source_manifest:
        raise FileNotFoundError(
            f"Missing {source_manifest_path}. Run embed_shards.py successfully before "
            "building Qdrant."
        )

    if args.target == "local":
        args.storage_dir.mkdir(parents=True, exist_ok=True)
        
    setup_logging(args.shards_dir / f"qdrant_build_{args.target}.log")
    build_manifest_path = args.shards_dir / f"qdrant_manifest_{args.target}.json"
    build_manifest = read_json(build_manifest_path, {"shards": {}})
    
    if args.recreate:
        build_manifest = {"shards": {}}

    completed = [
        (key, value)
        for key, value in sorted(source_manifest["shards"].items())
        if value.get("status") == "done"
    ]

    # Initialize client connections
    clients: list[QdrantClient] = []
    if args.target == "local":
        clients = [QdrantClient(path=str(args.storage_dir))]
    elif args.target == "cloud":
        clients = [QdrantClient(url=args.url, api_key=args.api_key)]
    elif args.target == "multi":
        with open(args.clusters_config, "r", encoding="utf-8") as f:
            config = json.load(f)
        clusters = config.get("clusters", [])
        if not clusters:
            raise ValueError("No clusters defined in config file.")
        clients = [QdrantClient(url=c["url"], api_key=c.get("api_key")) for c in clusters]

    num_clients = len(clients)

    # Prepare collections
    for client in clients:
        ensure_collection(client, args.collection, args.recreate, args.quantization)

    # Upload loop
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
        if args.include_text and "chunk_text" not in payload_df.columns:
            raise ValueError(
                "--include-text requires shards created with --include-text-in-payload"
            )
        vectors = np.load(vector_path, mmap_mode="r")
        if len(vectors) != payload_df.height:
            raise ValueError(f"Payload/vector row mismatch in shard {shard_key}")

        rows = payload_df.to_dicts()
        client_idx = shard_idx % num_clients
        client = clients[client_idx]

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
            "target_client": client_idx,
        }
        build_manifest["collection"] = args.collection
        build_manifest["include_text"] = args.include_text
        build_manifest["point_count"] = sum(c.count(args.collection, exact=True).count for c in clients)
        atomic_write_json(build_manifest_path, build_manifest)
        logging.info("Upserted shard %s to client %d", shard_key, client_idx)

    # Verification checks
    if num_clients == 1:
        expected = sum(item["rows"] for _, item in completed)
        actual = clients[0].count(args.collection, exact=True).count
        if actual != expected:
            raise ValueError(f"Qdrant count mismatch: expected {expected:,}, got {actual:,}")
        logging.info("Qdrant collection contains %s points", f"{actual:,}")

    for client in clients:
        client.close()

    if args.archive is not None and args.target == "local":
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        archive_base = args.archive.with_suffix("")
        result = shutil.make_archive(str(archive_base), "zip", args.storage_dir)
        logging.info("Created archive %s", result)


if __name__ == "__main__":
    main()
