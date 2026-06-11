import json
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import polars as pl
from qdrant_client import QdrantClient, models

import sys
sys.path.append(str(Path(__file__).resolve().parent))
from embedding_common import COLLECTION_NAME, MODEL_NAME, encode_texts, load_encoder, row_to_payload

class MultiQdrantRetriever:
    def __init__(self, clusters_config: Path, collection: str = COLLECTION_NAME,
                 model_name: str = MODEL_NAME, query_max_length: int = 512):
        with open(clusters_config, "r", encoding="utf-8") as f:
            config = json.load(f)
        self.clients = [
            QdrantClient(url=c["url"], api_key=c["api_key"])
            for c in config.get("clusters", [])
        ]
        self.collection = collection
        self.tokenizer, self.model, self.device, _ = load_encoder(model_name)
        self.query_max_length = query_max_length

    def close(self):
        for client in self.clients:
            client.close()

    def _query_single_client(self, client: QdrantClient, vector: list, top_k: int):
        try:
            res = client.query_points(
                collection_name=self.collection,
                query=vector,
                limit=top_k,
                with_payload=True
            )
            return [(point.score, point.payload or {}) for point in res.points]
        except Exception as e:
            print(f"Error querying cluster {client._client.configuration.host}: {e}")
            return []

    def search(self, query: str, top_k: int = 10) -> list[dict]:
        vector = encode_texts(
            [query], self.tokenizer, self.model, self.device,
            batch_size=1, max_length=self.query_max_length, is_query=True, show_progress=False
        )[0].tolist()

        # Run concurrent queries
        all_hits = []
        with ThreadPoolExecutor(max_workers=len(self.clients)) as executor:
            futures = [executor.submit(self._query_single_client, client, vector, top_k) for client in self.clients]
            for fut in futures:
                all_hits.extend(fut.result())

        # Sort and deduplicate
        all_hits.sort(key=lambda x: x[0], reverse=True)
        unique_hits = []
        seen = set()
        for score, payload in all_hits:
            chunk_id = payload.get("chunk_id")
            if chunk_id not in seen:
                seen.add(chunk_id)
                unique_hits.append({
                    "chunk_id": chunk_id,
                    "dense_score": score,
                    "payload": payload
                })
                if len(unique_hits) == top_k:
                    break
        return unique_hits
