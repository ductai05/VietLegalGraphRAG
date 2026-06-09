"""Evaluate sparse retrieval against a JSONL gold set."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.elastic_client import INDEX_ALIAS, build_elasticsearch_client, load_jsonl
from src.sparse_retriever import SparseRetriever


def id_set(values: Any) -> set[str]:
    if values in (None, ""):
        return set()
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    return {str(value) for value in values if value not in (None, "")}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--index-alias", default=INDEX_ALIAS)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-verify-certs", action="store_true")
    return parser.parse_args()


def relevance(hit: dict[str, Any], row: dict[str, Any]) -> int:
    chunk_ids = id_set(row.get("relevant_chunk_ids") or row.get("expected_chunk_ids"))
    doc_ids = id_set(row.get("relevant_doc_ids") or row.get("expected_doc_ids"))
    return int(
        str(hit.get("chunk_id")) in chunk_ids
        or str(hit.get("payload", {}).get("doc_id")) in doc_ids
    )


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.gold)
    client = build_elasticsearch_client(
        args.url,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        verify_certs=not args.no_verify_certs,
    )
    retriever = SparseRetriever(client, index_alias=args.index_alias)
    details = []
    try:
        for row in rows:
            query = row.get("query") or row.get("query_text")
            if not query:
                raise ValueError(f"Gold query is missing query text: {row}")
            hits = retriever.search(
                query,
                filters=row.get("filters"),
                top_k=args.top_k,
                expand=False,
            )
            rel = [relevance(hit, row) for hit in hits]
            first = next((index + 1 for index, value in enumerate(rel) if value), None)
            relevant_total = max(
                len(id_set(row.get("relevant_chunk_ids") or row.get("expected_chunk_ids"))),
                len(id_set(row.get("relevant_doc_ids") or row.get("expected_doc_ids"))),
                1,
            )
            recall = min(sum(rel) / relevant_total, 1.0)
            mrr = 1.0 / first if first else 0.0
            dcg = sum(value / math.log2(index + 2) for index, value in enumerate(rel))
            ideal_hits = min(relevant_total, args.top_k)
            idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
            details.append(
                {
                    "query": query,
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
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "details"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
