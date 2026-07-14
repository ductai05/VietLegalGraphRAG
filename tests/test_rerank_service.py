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

        def rerank(self, query, hits, top_k, model=None, timeout_ms=None, provider=None):
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


def test_jina_reranker_fallback_on_api_error(monkeypatch) -> None:
    from rerank_service import JinaReranker

    class MockResponse:
        def raise_for_status(self):
            raise Exception("API error")

    def mock_post(*args, **kwargs):
        return MockResponse()

    import requests
    monkeypatch.setattr(requests, "post", mock_post)

    hits = [_hit("a"), _hit("b")]
    reranker = JinaReranker(api_key="test-key", model="jina-reranker-v2-base-multilingual")

    result = reranker.rerank("query", hits, top_k=2)
    assert [hit.chunk_id for hit in result] == ["a", "b"]


def test_routing_reranker_routes_correctly() -> None:
    from rerank_service import RoutingReranker

    class DummyReranker:
        def __init__(self, name: str) -> None:
            self.name = name
            self.last_model = None

        def rerank(self, query, hits, top_k, model=None, timeout_ms=None, provider=None):
            self.last_model = model
            # return reversed to distinguish
            return list(reversed(hits))[:top_k]

    voyage = DummyReranker("voyage")
    jina = DummyReranker("jina")

    router = RoutingReranker(
        voyage_reranker=voyage,
        jina_reranker=jina,
        default_provider="voyage",
    )

    hits = [_hit("a"), _hit("b")]

    # Test route to voyage
    res1 = router.rerank("query", hits, top_k=2, provider="voyage", model="voyage-model")
    assert [h.chunk_id for h in res1] == ["b", "a"]
    assert voyage.last_model == "voyage-model"

    # Test route to jina
    res2 = router.rerank("query", hits, top_k=2, provider="jina", model="jina-model")
    assert [h.chunk_id for h in res2] == ["b", "a"]
    assert jina.last_model == "jina-model"

    # Test voyage default model mapping on jina routing
    router.rerank("query", hits, top_k=2, provider="jina", model="rerank-2.5")
    assert jina.last_model == "jina-ranker-v2-base-multilingual" or jina.last_model == "jina-reranker-v2-base-multilingual"

