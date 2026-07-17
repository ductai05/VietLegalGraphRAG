from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Protocol

from contracts import RetrievalHit


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        model: str | None = None,
        timeout_ms: int | None = None,
        provider: str | None = None,
    ) -> list[RetrievalHit]:
        ...


class NoopReranker:
    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        model: str | None = None,
        timeout_ms: int | None = None,
        provider: str | None = None,
    ) -> list[RetrievalHit]:
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

    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        model: str | None = None,
        timeout_ms: int | None = None,
        provider: str | None = None,
    ) -> list[RetrievalHit]:
        if not hits:
            return []
        documents = [format_rerank_document(hit) for hit in hits]
        rerank_model = model or self.model
        try:
            response = self._call_rerank(
                query=query,
                documents=documents,
                model=rerank_model,
                top_k=min(top_k, len(hits)),
                timeout_ms=timeout_ms,
            )
        except TimeoutError:
            logging.warning("Voyage rerank timed out; returning original retrieval order")
            return hits[:top_k]
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

    def _call_rerank(
        self,
        *,
        query: str,
        documents: list[str],
        model: str,
        top_k: int,
        timeout_ms: int | None,
    ) -> object:
        kwargs = {
            "query": query,
            "documents": documents,
            "model": model,
            "top_k": top_k,
        }
        if timeout_ms is None:
            return self.client.rerank(**kwargs)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self.client.rerank, **kwargs)
        try:
            return future.result(timeout=timeout_ms / 1000)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def _get_value(item: object, name: str) -> object | None:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


class JinaReranker:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.api_url = "https://api.jina.ai/v1/rerank"

    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        model: str | None = None,
        timeout_ms: int | None = None,
        provider: str | None = None,
    ) -> list[RetrievalHit]:
        if not hits:
            return []
        documents = [format_rerank_document(hit) for hit in hits]
        rerank_model = model or self.model
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": rerank_model,
            "query": query,
            "documents": documents,
            "top_n": min(top_k, len(hits))
        }

        try:
            timeout_sec = (timeout_ms / 1000.0) if timeout_ms else 30.0
            import requests
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=timeout_sec)
            response.raise_for_status()
            data = response.json()
        except Exception:
            logging.exception("Jina rerank failed; returning original retrieval order")
            return hits[:top_k]

        results = data.get("results", [])
        reranked: list[RetrievalHit] = []
        for item in results:
            index = item.get("index")
            if index is None:
                continue
            source_hit = hits[int(index)]
            score = item.get("relevance_score")
            if score is not None:
                source_hit.scores["rerank"] = float(score)
            reranked.append(source_hit)

        if not reranked:
            return hits[:top_k]
        for rank, hit in enumerate(reranked[:top_k], start=1):
            hit.rank = rank
        return reranked[:top_k]


class RoutingReranker:
    def __init__(self, voyage_reranker: Reranker, jina_reranker: Reranker, default_provider: str) -> None:
        self.voyage_reranker = voyage_reranker
        self.jina_reranker = jina_reranker
        self.default_provider = default_provider

    def rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        top_k: int,
        model: str | None = None,
        timeout_ms: int | None = None,
        provider: str | None = None,
    ) -> list[RetrievalHit]:
        active_provider = provider or self.default_provider
        active_provider = active_provider.lower() if active_provider else "noop"

        if active_provider == "voyage":
            return self.voyage_reranker.rerank(query, hits, top_k, model, timeout_ms)
        elif active_provider == "jina":
            # Map default voyage model to default jina model if needed
            jina_model = model
            if jina_model == "rerank-2.5":
                jina_model = "jina-reranker-v2-base-multilingual"
            return self.jina_reranker.rerank(query, hits, top_k, jina_model, timeout_ms)
        else:
            return hits[:top_k]
