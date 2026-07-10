from __future__ import annotations

import time


def _hit(chunk_id: str):
    from contracts import RetrievalHit

    return RetrievalHit(
        rank=1,
        chunk_id=chunk_id,
        doc_id="doc-1",
        title="Doc",
        document_number="01/2026/QH",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 1",
        text=f"text {chunk_id}",
    )


def test_retrieval_service_passes_request_timeout_to_reranker() -> None:
    from retrieval_modes import RetrievalRequest
    from retrieval_service import RetrievalService

    class FakeRetriever:
        def search(self, request, candidate_k):
            return [_hit("a"), _hit("b")]

    class CapturingReranker:
        def __init__(self) -> None:
            self.timeout_ms = None

        def rerank(self, query, hits, top_k, model=None, timeout_ms=None):
            self.timeout_ms = timeout_ms
            return hits[:top_k]

    reranker = CapturingReranker()
    service = RetrievalService(
        dense_retriever=None,
        sparse_retriever=FakeRetriever(),
        reranker=reranker,
    )
    request = RetrievalRequest(
        query="test",
        retrieval_mode="sparse",
        top_k=1,
        rerank={"enabled": True, "candidate_k": 2, "timeout_ms": 1234},
    )

    service.search(request)

    assert reranker.timeout_ms == 1234


def test_voyage_reranker_timeout_returns_original_order_quickly() -> None:
    from rerank_service import VoyageReranker

    class SlowClient:
        def rerank(self, **kwargs):
            time.sleep(0.2)
            return []

    hits = [_hit("a"), _hit("b")]
    reranker = VoyageReranker(client=SlowClient(), model="rerank-2.5")

    started = time.perf_counter()
    result = reranker.rerank("query", hits, top_k=2, timeout_ms=1)
    elapsed = time.perf_counter() - started

    assert [hit.chunk_id for hit in result] == ["a", "b"]
    assert elapsed < 0.15
