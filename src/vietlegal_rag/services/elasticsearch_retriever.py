from __future__ import annotations

import logging
from typing import Any

from contracts import AnswerContext, RetrievalHit
from retrieval_modes import RetrievalRequest


TEXT_QUERY_FIELDS = [
    "chunk_text^4",
    "chunk_text_vi^4",
    "chunk_text_folded^3",
    "contextual_text^2",
    "contextual_text_vi^2",
    "title^2",
    "title_vi^2",
    "title_folded^2",
    "section_path",
    "section_path_vi",
    "section_path_folded",
    "procedure_name",
    "procedure_name_vi",
    "procedure_name_folded",
    "issuing_authority",
    "issuing_authority_vi",
    "issuing_authority_folded",
    "document_number",
    "document_number_norm",
]

TEXT_EXACT_FIELDS = {
    "title",
    "section_path",
    "procedure_name",
    "issuing_authority",
}


class ElasticsearchTextRetriever:
    def __init__(self, client: Any, index: str) -> None:
        self.client = client
        self.index = index

    def search(self, request: RetrievalRequest, candidate_k: int) -> list[RetrievalHit]:
        response = self.client.search(
            index=self.index,
            size=candidate_k,
            query={
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": request.query,
                                "fields": TEXT_QUERY_FIELDS,
                                "type": "best_fields",
                                "operator": "or",
                            }
                        }
                    ],
                    "filter": build_filter_clauses(request.filters),
                }
            },
            source_excludes=["vector"],
        )
        raw_hits = response.get("hits", {}).get("hits", [])
        hits = [
            retrieval_hit_from_elasticsearch(rank, raw_hit)
            for rank, raw_hit in enumerate(raw_hits, start=1)
        ]
        return hits


class ElasticsearchDenseRetriever:
    """kNN retrieval over the `vector` field.

    Shares filter building and hit mapping with the BM25 retriever so both
    paths return identical `RetrievalHit` shapes; only the score key differs
    (``scores={"dense": ...}``). Embedding or search failures degrade to an
    empty hit list (dense contributes nothing; sparse still answers).
    """

    def __init__(
        self,
        client: Any,
        index: str,
        embedder: Any,
        vector_field: str = "vector",
        num_candidates_factor: int = 4,
        min_num_candidates: int = 100,
    ) -> None:
        self.client = client
        self.index = index
        self.embedder = embedder
        self.vector_field = vector_field
        self.num_candidates_factor = num_candidates_factor
        self.min_num_candidates = min_num_candidates

    def search(self, request: RetrievalRequest, candidate_k: int) -> list[RetrievalHit]:
        try:
            query_vector = self.embedder.embed_query(request.query)
            knn: dict[str, Any] = {
                "field": self.vector_field,
                "query_vector": query_vector,
                "k": candidate_k,
                "num_candidates": max(
                    candidate_k * self.num_candidates_factor,
                    self.min_num_candidates,
                ),
            }
            filter_clauses = build_filter_clauses(request.filters)
            if filter_clauses:
                knn["filter"] = filter_clauses
            response = self.client.search(
                index=self.index,
                knn=knn,
                size=candidate_k,
                source_excludes=[self.vector_field],
            )
        except Exception:
            logging.exception("Dense retrieval failed; returning no dense hits")
            return []
        raw_hits = response.get("hits", {}).get("hits", [])
        return [
            retrieval_hit_from_elasticsearch(rank, raw_hit, score_key="dense")
            for rank, raw_hit in enumerate(raw_hits, start=1)
        ]


class ElasticsearchGraphChunkFetcher:
    """Fetch one lexical chunk for each graph-neighbor document."""

    def __init__(self, client: Any, index: str, per_doc_size: int = 1) -> None:
        self.client = client
        self.index = index
        self.per_doc_size = per_doc_size

    def __call__(
        self,
        query: str,
        related_documents: list[dict[str, str]],
    ) -> list[AnswerContext]:
        contexts: list[AnswerContext] = []
        seen_chunks: set[str] = set()
        for related in related_documents:
            doc_id = related.get("doc_id")
            if not doc_id:
                continue
            response = self.client.search(
                index=self.index,
                size=self.per_doc_size,
                query={
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": TEXT_QUERY_FIELDS,
                                    "type": "best_fields",
                                    "operator": "or",
                                }
                            }
                        ],
                        "filter": [{"term": {"doc_id": doc_id}}],
                    }
                },
                source_excludes=["vector"],
            )
            raw_hits = response.get("hits", {}).get("hits", [])
            for raw_hit in raw_hits:
                hit = retrieval_hit_from_elasticsearch(1, raw_hit)
                if hit.chunk_id in seen_chunks:
                    continue
                seen_chunks.add(hit.chunk_id)
                contexts.append(
                    AnswerContext(
                        source="graph",
                        chunk_id=hit.chunk_id,
                        doc_id=hit.doc_id,
                        title=hit.title,
                        text=hit.text,
                        citation=hit.citation,
                        relation=related.get("relation"),
                        raw_label=related.get("raw_label"),
                    )
                )
        return contexts


def build_filter_clauses(filters: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not filters:
        return []
    clauses: list[dict[str, Any]] = []
    ranges = filters.get("ranges", {})
    for field, expected in filters.items():
        if field == "ranges":
            continue
        target_field = f"{field}.keyword" if field in TEXT_EXACT_FIELDS else field
        if field == "doc_id":
            expected = (
                [str(value) for value in expected]
                if isinstance(expected, list)
                else str(expected)
            )
        if isinstance(expected, list):
            clauses.append({"terms": {target_field: expected}})
        else:
            clauses.append({"term": {target_field: expected}})
    for field, bounds in ranges.items():
        clauses.append({"range": {field: bounds}})
    return clauses


def retrieval_hit_from_elasticsearch(
    rank: int,
    hit: dict[str, Any],
    score_key: str = "bm25",
) -> RetrievalHit:
    source = dict(hit.get("_source") or {})
    source.pop("vector", None)
    chunk_id = str(source.get("chunk_id") or hit.get("_id") or "")
    section_path = format_section_path(source.get("section_path"))
    text = str(
        source.get("chunk_text")
        or source.get("contextual_text")
        or source.get("chunk_text_vi")
        or ""
    )
    document_number = str(source.get("document_number") or "")
    title = str(source.get("title") or "")
    return RetrievalHit(
        rank=rank,
        chunk_id=chunk_id,
        doc_id=str(source.get("doc_id") or ""),
        title=title,
        document_number=document_number,
        legal_type=str(source.get("legal_type") or ""),
        effect_status=str(source.get("effect_status") or ""),
        section_path=section_path,
        text=text,
        scores={score_key: float(hit.get("_score") or 0.0)},
        citation=format_citation(
            document_number=document_number,
            title=title,
            section_path=section_path,
            chunk_id=chunk_id,
        ),
    )


def format_section_path(value: Any) -> str:
    if isinstance(value, list):
        return " > ".join(str(item) for item in value if item is not None)
    if value is None:
        return ""
    return str(value)


def format_citation(
    *,
    document_number: str,
    title: str,
    section_path: str,
    chunk_id: str,
) -> str:
    parts = [document_number, title, section_path, f"chunk_id: {chunk_id}"]
    return " | ".join(part for part in parts if part)
