"""Query Elasticsearch BM25 sparse index and format RAG hits."""

from __future__ import annotations

import argparse
import json
from typing import Any

from elasticsearch import Elasticsearch

from src.elastic_client import (
    FOLDED_SEARCH_FIELDS,
    INDEX_ALIAS,
    RAW_SEARCH_FIELDS,
    VI_SEARCH_FIELDS,
    build_elasticsearch_client,
    build_filter_clauses,
    format_citation,
    payload_from_source,
)
from src.normalizer import fold_vietnamese, normalize_document_number, text_value
from src.query_router import QueryRoute, route_query
from src.tokenizer import tokenize_vi


class SparseRetriever:
    def __init__(
        self,
        elasticsearch_client: Elasticsearch,
        index_alias: str = INDEX_ALIAS,
    ) -> None:
        self.client = elasticsearch_client
        self.index_alias = index_alias

    def close(self) -> None:
        self.client.close()

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int = 20,
        expand: bool = True,
    ) -> list[dict[str, Any]]:
        if top_k <= 0 or not text_value(query):
            return []
        route = route_query(query)
        hits: list[dict[str, Any]] = []
        if route.kind == "exact":
            hits = self._run_search(self._exact_query(query, route, filters), top_k)
            if len(hits) >= top_k:
                return self._expand_hits(hits, expand)
        bm25_hits = self._run_search(self._bm25_query(query, filters), top_k)
        merged = self._merge_hits(hits, bm25_hits, top_k)
        return self._expand_hits(merged, expand)

    def _run_search(self, body: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
        response = self.client.search(
            index=self.index_alias,
            query=body["query"],
            size=top_k,
        )
        hits = []
        for rank, hit in enumerate(response.get("hits", {}).get("hits", []), start=1):
            source = hit.get("_source") or {}
            payload = payload_from_source(source)
            chunk_id = payload.get("chunk_id") or hit.get("_id")
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "score": hit.get("_score", 0.0),
                    "retriever": "sparse",
                    "rank": rank,
                    "payload": payload,
                    "citation": format_citation(payload),
                    "optional_expanded_context": None,
                }
            )
        return hits

    def _exact_query(
        self,
        query: str,
        route: QueryRoute,
        filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        should = []
        normalized = route.normalized_document_number or normalize_document_number(query)
        raw = text_value(query)
        if normalized:
            should.append({"term": {"document_number_norm": {"value": normalized, "boost": 30.0}}})
        if raw:
            should.append({"term": {"document_number": {"value": raw, "boost": 10.0}}})
            should.append({"term": {"chunk_id": {"value": raw, "boost": 5.0}}})
        if route.internal_id is not None:
            should.append({"term": {"doc_id": {"value": route.internal_id, "boost": 8.0}}})
        return {
            "query": {
                "bool": {
                    "should": should,
                    "minimum_should_match": 1,
                    "filter": build_filter_clauses(filters),
                }
            }
        }

    def _bm25_query(self, query: str, filters: dict[str, Any] | None) -> dict[str, Any]:
        query_vi = tokenize_vi(query)
        query_folded = fold_vietnamese(query_vi or query)
        should = [
            {
                "multi_match": {
                    "query": query_vi or query,
                    "fields": VI_SEARCH_FIELDS,
                    "type": "best_fields",
                }
            },
            {
                "multi_match": {
                    "query": query_folded,
                    "fields": FOLDED_SEARCH_FIELDS,
                    "type": "best_fields",
                }
            },
            {
                "multi_match": {
                    "query": query,
                    "fields": RAW_SEARCH_FIELDS,
                    "type": "best_fields",
                }
            },
        ]
        return {
            "query": {
                "bool": {
                    "should": should,
                    "minimum_should_match": 1,
                    "filter": build_filter_clauses(filters),
                }
            }
        }

    def _merge_hits(
        self,
        primary: list[dict[str, Any]],
        secondary: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        merged = []
        seen = set()
        for hit in [*primary, *secondary]:
            chunk_id = hit.get("chunk_id")
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            merged.append(hit)
            if len(merged) >= top_k:
                break
        for rank, hit in enumerate(merged, start=1):
            hit["rank"] = rank
        return merged

    def _expand_hits(self, hits: list[dict[str, Any]], expand: bool) -> list[dict[str, Any]]:
        if not expand or not hits:
            return hits
        expansion_ids = []
        for hit in hits:
            payload = hit.get("payload") or {}
            if payload.get("chunk_type") == "table_summary" and payload.get("raw_table_id"):
                expansion_ids.append(payload["raw_table_id"])
            elif payload.get("chunk_type") == "procedure_record":
                expansion_ids.extend(
                    value for value in [payload.get("parent_id"), payload.get("raw_table_id")] if value
                )
            elif payload.get("chunk_type") == "clause_group" and payload.get("parent_id"):
                expansion_ids.append(payload["parent_id"])
        lookup = self._lookup_chunk_text(list(dict.fromkeys(expansion_ids)))
        for hit in hits:
            payload = hit.get("payload") or {}
            target_id = None
            if payload.get("chunk_type") == "table_summary":
                target_id = payload.get("raw_table_id")
            elif payload.get("chunk_type") == "procedure_record":
                target_id = payload.get("parent_id") or payload.get("raw_table_id")
            elif payload.get("chunk_type") == "clause_group":
                target_id = payload.get("parent_id")
            if target_id in lookup:
                hit["optional_expanded_context"] = lookup[target_id]
        return hits

    def _lookup_chunk_text(self, chunk_ids: list[str]) -> dict[str, str]:
        if not chunk_ids:
            return {}
        response = self.client.mget(
            index=self.index_alias,
            ids=chunk_ids,
        )
        lookup = {}
        for doc in response.get("docs", []):
            if not doc.get("found"):
                continue
            source = doc.get("_source") or {}
            lookup[source.get("chunk_id") or doc.get("_id")] = source.get("chunk_text", "")
        return lookup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--index-alias", default=INDEX_ALIAS)
    parser.add_argument("--query", required=True)
    parser.add_argument("--filters", default=None, help="JSON object with exact/range filters.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-expand", action="store_true")
    parser.add_argument("--no-verify-certs", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = build_elasticsearch_client(
        args.url,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        verify_certs=not args.no_verify_certs,
    )
    retriever = SparseRetriever(client, index_alias=args.index_alias)
    try:
        hits = retriever.search(
            args.query,
            filters=json.loads(args.filters) if args.filters else None,
            top_k=args.top_k,
            expand=not args.no_expand,
        )
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
