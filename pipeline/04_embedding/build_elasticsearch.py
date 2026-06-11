import argparse
from pathlib import Path
import numpy as np
import polars as pl
from elasticsearch import Elasticsearch, helpers

import sys
sys.path.append(str(Path(__file__).resolve().parent))
from embedding_common import read_json, stable_point_id

def parse_args():
    parser = argparse.ArgumentParser(description="Upload vector shards to Elastic Cloud")
    parser.add_argument("--shards-dir", type=Path, required=True)
    parser.add_argument("--cloud-id", required=True, help="Elastic Cloud ID")
    parser.add_argument("--api-key", required=True, help="Elastic API Key")
    parser.add_argument("--index", default="legal_chunks_dense_v1")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--upsert-batch", type=int, default=500)
    return parser.parse_args()

def ensure_index(es: Elasticsearch, index: str, recreate: bool):
    if recreate and es.indices.exists(index=index):
        es.indices.delete(index=index)
    if not es.indices.exists(index=index):
        mapping = {
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "doc_id": {"type": "integer"},
                    "chunk_type": {"type": "keyword"},
                    "title": {"type": "text"},
                    "legal_type": {"type": "keyword"},
                    "issuing_authority": {"type": "keyword"},
                    "effect_status": {"type": "keyword"},
                    "vector": {
                        "type": "dense_vector",
                        "dims": 1024,
                        "index": True,
                        "similarity": "cosine"
                    }
                }
            }
        }
        es.indices.create(index=index, body=mapping)
        print(f"Created index {index}")

def main():
    args = parse_args()
    source_manifest_path = args.shards_dir / "manifest.json"
    source_manifest = read_json(source_manifest_path)
    
    es = Elasticsearch(cloud_id=args.cloud_id, api_key=args.api_key)
    ensure_index(es, args.index, args.recreate)
    
    completed = sorted([
        (key, info) for key, info in source_manifest["shards"].items()
        if info.get("status") == "done"
    ])
    
    print(f"Uploading {len(completed)} shards to Elastic Cloud...")
    for shard_key, shard_info in completed:
        payload_path = args.shards_dir / shard_info["payload"]
        vector_path = args.shards_dir / shard_info["vectors"]
        payload_df = pl.read_parquet(payload_path)
        vectors = np.load(vector_path, mmap_mode="r")
        rows = payload_df.to_dicts()
        
        actions = []
        for index in range(payload_df.height):
            action = {
                "_index": args.index,
                "_id": stable_point_id(rows[index]["chunk_id"]),
                "_source": {
                    "chunk_id": rows[index]["chunk_id"],
                    "doc_id": rows[index]["doc_id"],
                    "chunk_type": rows[index]["chunk_type"],
                    "title": rows[index].get("title", ""),
                    "legal_type": rows[index].get("legal_type", ""),
                    "issuing_authority": rows[index].get("issuing_authority", ""),
                    "effect_status": rows[index].get("effect_status", ""),
                    "vector": vectors[index].astype(np.float32).tolist()
                }
            }
            actions.append(action)
            
            if len(actions) >= args.upsert_batch:
                helpers.bulk(es, actions)
                actions = []
                
        if actions:
            helpers.bulk(es, actions)
            
        print(f"  Uploaded shard {shard_key}")
    print("Elastic Cloud indexing complete.")

if __name__ == "__main__":
    main()
