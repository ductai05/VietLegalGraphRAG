import argparse
import logging
from pathlib import Path
import numpy as np
import polars as pl
from qdrant_client import QdrantClient, models

# Import common variables and helper utilities
import sys
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

def parse_args():
    parser = argparse.ArgumentParser(description="Upload shards to Qdrant Cloud with Quantization")
    parser.add_argument("--shards-dir", type=Path, required=True, help="Directory containing shards")
    parser.add_argument("--url", required=True, help="Qdrant Cloud URL")
    parser.add_argument("--api-key", required=True, help="Qdrant Cloud API Key")
    parser.add_argument("--collection", default=COLLECTION_NAME)
    parser.add_argument("--upsert-batch", type=int, default=200)
    parser.add_argument("--quantization", choices=["none", "scalar", "pq"], default="pq",
                        help="Quantization type (none, scalar, pq). Default is pq for free tier compatibility.")
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args()

def ensure_collection(client: QdrantClient, name: str, recreate: bool, quantization: str) -> None:
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
        # PQ64 reduces vector size from 4096 bytes to 64 bytes
        quantization_config = models.ProductQuantization(
            product=models.ProductQuantizationConfig(
                compression=models.CompressionRatio.X64,
                always_ram=False,
            )
        )

    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
        hnsw_config=models.HnswConfigDiff(
            m=16,
            ef_construct=100,
            full_scan_threshold=10_000,
        ),
        optimizers_config=models.OptimizersConfigDiff(default_segment_number=4),
        quantization_config=quantization_config
    )

def main():
    args = parse_args()
    source_manifest_path = args.shards_dir / "manifest.json"
    source_manifest = read_json(source_manifest_path)
    if not source_manifest:
        raise FileNotFoundError(f"Missing {source_manifest_path}.")
        
    setup_logging(args.shards_dir / "qdrant_cloud_build.log")
    build_manifest_path = args.shards_dir / "qdrant_cloud_manifest.json"
    build_manifest = read_json(build_manifest_path, {"shards": {}})
    
    client = QdrantClient(url=args.url, api_key=args.api_key)
    ensure_collection(client, args.collection, args.recreate, args.quantization)
    if args.recreate:
        build_manifest = {"shards": {}}

    completed = [
        (key, value)
        for key, value in sorted(source_manifest["shards"].items())
        if value.get("status") == "done"
    ]
    for shard_key, shard_info in completed:
        previous = build_manifest["shards"].get(shard_key, {})
        if previous.get("status") == "done" and previous.get("rows") == shard_info["rows"]:
            logging.info("Skipping upserted shard %s", shard_key)
            continue
            
        payload_path = args.shards_dir / shard_info["payload"]
        vector_path = args.shards_dir / shard_info["vectors"]
        payload_df = pl.read_parquet(payload_path)
        vectors = np.load(vector_path, mmap_mode="r")

        rows = payload_df.to_dicts()
        for indices in batched(range(payload_df.height), args.upsert_batch):
            points = [
                models.PointStruct(
                    id=stable_point_id(rows[index]["chunk_id"]),
                    vector=vectors[index].astype(np.float32).tolist(),
                    payload=row_to_payload(rows[index], include_text=False),
                )
                for index in indices
            ]
            client.upsert(args.collection, points=points, wait=True)

        build_manifest["shards"][shard_key] = {
            "status": "done",
            "rows": payload_df.height,
        }
        build_manifest["point_count"] = client.count(args.collection, exact=True).count
        atomic_write_json(build_manifest_path, build_manifest)
        logging.info("Upserted shard %s to Cloud", shard_key)

    client.close()
    print(f"Upload complete. Quantization={args.quantization}")

if __name__ == "__main__":
    main()
