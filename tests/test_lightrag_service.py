import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALUATION_DIR = ROOT / "pipeline" / "07_evaluation"
sys.path.insert(0, str(EVALUATION_DIR))


class FakeRetrievalService:
    def __init__(self):
        self.calls = []

    def search(self, request):
        self.calls.append(request)
        return [{"chunk_id": "c1", "text": "retrieved text"}]


class FakeGraphRetriever:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def retrieve(self, query, retrieval_hits, max_hops):
        self.calls.append((query, retrieval_hits, max_hops))
        if self.fail:
            raise RuntimeError("neo4j unavailable")
        return [{"doc_id": "d1", "relation": "CITES"}]


class FakeAnswerService:
    def __init__(self):
        self.calls = []

    def answer(self, query, contexts, temperature):
        self.calls.append((query, contexts, temperature))
        return {
            "answer": "answer text",
            "citations": [{"chunk_id": "c1"}],
        }


def test_lightrag_service_merges_retrieval_graph_and_answer_contexts():
    from lightrag_service import LightRAGService
    from retrieval_modes import RetrievalRequest

    retrieval = FakeRetrievalService()
    graph = FakeGraphRetriever()
    answer = FakeAnswerService()
    service = LightRAGService(retrieval, graph, answer)

    result = service.answer(
        RetrievalRequest(
            query="Van ban nao dan chieu den quy dinh nay?",
            llm={"temperature": 0.4},
            graph={"enabled": True, "use_lightrag": True, "max_hops": 2},
        )
    )

    assert result["answer"] == "answer text"
    assert result["citations"] == [{"chunk_id": "c1"}]
    assert result["graph_context"] == [{"doc_id": "d1", "relation": "CITES"}]
    assert result["retrieval_trace"]["execution_mode"] == "hybrid_rerank"
    assert result["retrieval_trace"]["lightrag_enabled"] is True
    assert graph.calls[0][2] == 2
    assert answer.calls[0][2] == 0.4


def test_lightrag_service_falls_back_when_graph_retrieval_fails():
    from lightrag_service import LightRAGService
    from retrieval_modes import RetrievalRequest

    service = LightRAGService(
        FakeRetrievalService(),
        FakeGraphRetriever(fail=True),
        FakeAnswerService(),
    )

    result = service.answer(RetrievalRequest(query="q"))

    assert result["answer"] == "answer text"
    assert result["graph_context"] == []
    assert result["retrieval_trace"]["lightrag_enabled"] is False
    assert "neo4j unavailable" in result["retrieval_trace"]["lightrag_error"]
