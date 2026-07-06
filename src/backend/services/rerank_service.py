from __future__ import annotations

from typing import Protocol

from contracts import RetrievalHit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        ...


class NoopReranker:
    def rerank(self, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        return hits[:top_k]
