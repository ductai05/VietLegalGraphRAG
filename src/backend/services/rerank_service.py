from __future__ import annotations

import logging
from typing import Protocol

from contracts import RetrievalHit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        ...


class NoopReranker:
    def rerank(self, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        return hits[:top_k]


def format_rerank_document(hit: RetrievalHit) -> str:
    return "\n".join(
        part
        for part in [
            f"Loại văn bản: {hit.legal_type}",
            f"Số hiệu: {hit.document_number}",
            f"Tiêu đề: {hit.title}",
            f"Tình trạng hiệu lực: {hit.effect_status}",
            f"Mục: {hit.section_path}",
            f"Nội dung: {hit.text}",
        ]
        if part.split(": ", 1)[1]
    )


class VoyageReranker:
    def __init__(self, client: object, model: str, batch_size: int = 8) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.client = client
        self.model = model
        self.batch_size = batch_size

    def rerank(self, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        if not hits:
            return []
        documents = [format_rerank_document(hit) for hit in hits]
        try:
            response = self.client.rerank(
                query=query,
                documents=documents,
                model=self.model,
                top_k=min(top_k, len(hits)),
            )
        except Exception:
            logging.exception("Voyage rerank failed; returning original retrieval order")
            return hits[:top_k]

        results = getattr(response, "results", response)
        reranked: list[RetrievalHit] = []
        for item in results:
            index = _get_value(item, "index")
            if index is None:
                continue
            source_hit = hits[int(index)]
            score = _get_value(item, "relevance_score")
            if score is not None:
                source_hit.scores["rerank"] = float(score)
            reranked.append(source_hit)

        if not reranked:
            return hits[:top_k]
        for rank, hit in enumerate(reranked[:top_k], start=1):
            hit.rank = rank
        return reranked[:top_k]


def _get_value(item: object, name: str) -> object | None:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)
