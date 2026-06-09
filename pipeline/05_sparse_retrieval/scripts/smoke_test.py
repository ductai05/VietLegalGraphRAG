"""Run sparse retrieval smoke queries and print compact results."""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--index-alias", default=INDEX_ALIAS)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-verify-certs", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.queries)
    client = build_elasticsearch_client(
        args.url,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        verify_certs=not args.no_verify_certs,
    )
    retriever = SparseRetriever(client, index_alias=args.index_alias)
    try:
        for row in rows:
            query = row.get("query") or row.get("query_text")
            if not query:
                raise ValueError(f"Smoke query is missing query text: {row}")
            top_k = int(row.get("top_k") or args.top_k)
            hits = retriever.search(
                query,
                filters=row.get("filters"),
                top_k=top_k,
                expand=False,
            )
            expected_chunks = id_set(row.get("expected_chunk_ids"))
            expected_docs = id_set(row.get("expected_doc_ids"))
            matched = any(
                str(hit.get("chunk_id")) in expected_chunks
                or str(hit.get("payload", {}).get("doc_id")) in expected_docs
                for hit in hits
            )
            print(
                json.dumps(
                    {
                        "query_id": row.get("query_id"),
                        "query": query,
                        "matched_expected": matched if (expected_chunks or expected_docs) else None,
                        "top_chunk_ids": [hit["chunk_id"] for hit in hits],
                        "top_citations": [hit["citation"] for hit in hits[:3]],
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
