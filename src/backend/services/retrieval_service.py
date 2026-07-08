from __future__ import annotations

from typing import Protocol

from contracts import RetrievalHit
from rerank_service import NoopReranker, Reranker
from retrieval_modes import RetrievalRequest


class Retriever(Protocol):
    def search(self, request: RetrievalRequest, candidate_k: int) -> list[RetrievalHit]:
        ...


class FusionRetriever:
    def __init__(self, k: int = 60) -> None:
        self.k = k

    def merge(
        self,
        dense_hits: list[RetrievalHit],
        sparse_hits: list[RetrievalHit],
        top_k: int,
    ) -> list[RetrievalHit]:
        by_chunk: dict[str, RetrievalHit] = {}
        rrf_scores: dict[str, float] = {}

        for source_hits in (dense_hits, sparse_hits):
            for rank, hit in enumerate(source_hits, start=1):
                if hit.chunk_id not in by_chunk:
                    by_chunk[hit.chunk_id] = hit
                else:
                    by_chunk[hit.chunk_id].scores.update(hit.scores)
                rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + 1.0 / (self.k + rank)

        merged = list(by_chunk.values())
        for hit in merged:
            hit.scores["rrf"] = rrf_scores[hit.chunk_id]

        merged.sort(key=lambda item: item.scores["rrf"], reverse=True)
        for rank, hit in enumerate(merged, start=1):
            hit.rank = rank
        return merged[:top_k]


class RetrievalService:
    def __init__(
        self,
        dense_retriever: Retriever | None,
        sparse_retriever: Retriever,
        fusion_retriever: FusionRetriever | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        # A dense retriever identical to the sparse one is treated as absent:
        # hybrid must not run the same BM25 query twice.
        if dense_retriever is sparse_retriever:
            dense_retriever = None
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.fusion_retriever = fusion_retriever or FusionRetriever()
        self.reranker = reranker or NoopReranker()

    @property
    def dense_enabled(self) -> bool:
        return self.dense_retriever is not None

    def search(self, request: RetrievalRequest) -> list[RetrievalHit]:
        candidate_k = request.rerank.candidate_k if request.rerank.enabled else request.top_k
        if request.retrieval_mode == "sparse" or self.dense_retriever is None:
            # Dense/hybrid degrade to a single BM25 pass when no embedder is
            # configured (runtime carries a dense.not_configured warning).
            hits = self.sparse_retriever.search(request, candidate_k)
        elif request.retrieval_mode == "dense":
            hits = self.dense_retriever.search(request, candidate_k)
        else:
            dense_hits = self.dense_retriever.search(request, candidate_k)
            sparse_hits = self.sparse_retriever.search(request, candidate_k)
            hits = self.fusion_retriever.merge(dense_hits, sparse_hits, candidate_k)

        if request.rerank.enabled:
            return self.reranker.rerank(
                request.query,
                hits,
                request.top_k,
                model=request.rerank.model,
            )
        return hits[:request.top_k]
