import argparse
import json
import logging
from pathlib import Path
import numpy as np
import polars as pl
from qdrant_client import QdrantClient, models

import sys
sys.path.append(str(Path(__file__).resolve().parent))
from embedding_common import (
    COLLECTION_NAME,
    VECTOR_SIZE,
    batched,
    read_json,
    row_to_payload,
    setup_logging,
    stable_point_id,
)

def parse_args():
    parser = argparse.ArgumentParser(description="Upload shards partitioned across multiple Qdrant clusters")
    parser.add_argument("--shards-dir", type=Path, required=True)
    parser.add_argument("--clusters-config", type=Path, required=True, help="Path to qdrant_clusters.json")
    parser.add_argument("--collection", default=COLLECTION_NAME)
    parser.add_argument("--upsert-batch", type=int, default=200)
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args()

def main():
    args = parse_args()
    setup_logging(args.shards_dir / "qdrant_multi_build.log")
    
    with open(args.clusters_config, "r", encoding="utf-8") as f:
        config = json.load(f)
    clusters = config.get("clusters", [])
    num_clusters = len(clusters)
    if num_clusters == 0:
        raise ValueError("No clusters defined in config.")
        
    source_manifest_path = args.shards_dir / "manifest.json"
    source_manifest = read_json(source_manifest_path)
    
    # Partition shards
    completed_shards = sorted([
        (key, info) for key, info in source_manifest["shards"].items()
        if info.get("status") == "done"
    ])
    
    print(f"Total shards to partition: {len(completed_shards)} across {num_clusters} clusters.")
    
    for i, cluster in enumerate(clusters):
        client = QdrantClient(url=cluster["url"], api_key=cluster["api_key"])
        if args.recreate and client.collection_exists(args.collection):
            client.delete_collection(args.collection)
            
        if not client.collection_exists(args.collection):
            client.create_collection(
                collection_name=args.collection,
                vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
                on_disk_payload=True
            )
            
        # Select shards assigned to this cluster index
        assigned = [item for idx, item in enumerate(completed_shards) if idx % num_clusters == i]
        print(f"Cluster {i+1}/{num_clusters} ({cluster['url']}): uploading {len(assigned)} shards...")
        
        for shard_key, shard_info in assigned:
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
            logging.info("Uploaded shard %s to Cluster %s", shard_key, i)
        client.close()
    print("Multi-cluster upload completed successfully!")

if __name__ == "__main__":
    main()
