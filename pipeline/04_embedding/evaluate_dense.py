"""Evaluate dense retrieval against a JSONL gold set."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from dense_retrieval import DenseRetriever
from embedding_common import COLLECTION_NAME, MODEL_NAME


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--storage-dir", type=Path)
    target.add_argument("--url")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--chunks", type=Path, default=None)
    parser.add_argument("--collection", default=COLLECTION_NAME)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default=None)
    parser.add_argument("--cache-dir", default=None)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def relevance(hit: dict[str, Any], row: dict[str, Any]) -> int:
    chunk_ids = set(row.get("relevant_chunk_ids") or [])
    doc_ids = set(row.get("relevant_doc_ids") or [])
    return int(
        hit.get("chunk_id") in chunk_ids
        or hit.get("payload", {}).get("doc_id") in doc_ids
    )


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.gold)
    retriever = DenseRetriever(
        args.storage_dir,
        url=args.url,
        api_key=args.api_key,
        collection=args.collection,
        model_name=args.model,
        chunks_path=args.chunks,
        device=args.device,
        cache_dir=args.cache_dir,
    )
    details = []
    try:
        for row in rows:
            hits = retriever.search(
                row["query"],
                filters=row.get("filters"),
                top_k=args.top_k,
                expand=False,
            )
            rel = [relevance(hit, row) for hit in hits]
            first = next((index + 1 for index, value in enumerate(rel) if value), None)
            relevant_total = max(
                len(row.get("relevant_chunk_ids") or []),
                len(row.get("relevant_doc_ids") or []),
                1,
            )
            recall = min(sum(rel) / relevant_total, 1.0)
            mrr = 1.0 / first if first else 0.0
            dcg = sum(value / math.log2(index + 2) for index, value in enumerate(rel))
            ideal_hits = min(relevant_total, args.top_k)
            idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
            details.append(
                {
                    "query": row["query"],
                    "group": row.get("group", "unknown"),
                    "recall": recall,
                    "mrr": mrr,
                    "ndcg": dcg / idcg if idcg else 0.0,
                    "top_chunk_ids": [hit["chunk_id"] for hit in hits],
                }
            )
    finally:
        retriever.close()

    def mean(key: str, subset: list[dict[str, Any]]) -> float:
        return sum(item[key] for item in subset) / len(subset) if subset else 0.0

    groups = sorted({item["group"] for item in details})
    report = {
        "queries": len(details),
        f"recall@{args.top_k}": mean("recall", details),
        f"mrr@{args.top_k}": mean("mrr", details),
        f"ndcg@{args.top_k}": mean("ndcg", details),
        "by_group": {
            group: {
                "queries": len(subset := [item for item in details if item["group"] == group]),
                f"recall@{args.top_k}": mean("recall", subset),
                f"mrr@{args.top_k}": mean("mrr", subset),
                f"ndcg@{args.top_k}": mean("ndcg", subset),
            }
            for group in groups
        },
        "details": details,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, indent=2))


if __name__ == "__main__":
    main()
