from contracts import AnswerContext, GraphContext, RetrievalHit
from lightrag_service import LightRAGService
from retrieval_modes import RetrievalRequest


class FakeRetrievalService:
    def search(self, request):
        return [
            RetrievalHit(
                rank=1,
                chunk_id="chunk:1:000001",
                doc_id="1",
                title="Doc 1",
                document_number="01/2026/QH",
                legal_type="Luat",
                effect_status="Con hieu luc",
                section_path="Dieu 1",
                text="retrieved text",
                scores={},
                citation="Doc 1, Dieu 1",
            )
        ]


class FakeGraphRetriever:
    def __init__(self, fail=False):
        self.fail = fail

    def retrieve(self, query, retrieval_hits, max_hops):
        if self.fail:
            raise RuntimeError("neo4j unavailable")
        return GraphContext(
            center=None,
            related_chunks=[
                AnswerContext(
                    source="graph",
                    chunk_id="chunk:2:000001",
                    doc_id="2",
                    title="Doc 2",
                    text="graph text",
                    citation="Doc 2",
                    relation="CITES",
                    raw_label="Van ban can cu",
                )
            ],
            query_intent="citation",
        )


class FakeAnswerService:
    def __init__(self):
        self.calls = []

    def answer(self, query, contexts, temperature):
        self.calls.append((query, contexts, temperature))
        return {"answer": "answer text", "citations": [{"chunk_id": contexts[0].chunk_id}]}


def test_lightrag_service_merges_retrieval_graph_and_answer_contexts() -> None:
    answer = FakeAnswerService()
    service = LightRAGService(FakeRetrievalService(), FakeGraphRetriever(), answer)

    result = service.answer(
        RetrievalRequest(
            query="Van ban nao dan chieu den quy dinh nay?",
            llm={"temperature": 0.4},
            graph={"enabled": True, "use_lightrag": True, "max_hops": 2},
        )
    )

    assert result["answer"] == "answer text"
    assert result["retrieval_trace"]["execution_mode"] == "hybrid_rerank"
    assert result["retrieval_trace"]["lightrag_enabled"] is True
    assert len(answer.calls[0][1]) == 2
    assert answer.calls[0][2] == 0.4


def test_lightrag_service_falls_back_when_graph_retrieval_fails() -> None:
    service = LightRAGService(
        FakeRetrievalService(),
        FakeGraphRetriever(fail=True),
        FakeAnswerService(),
    )

    result = service.answer(RetrievalRequest(query="q"))

    assert result["graph_context"] == {}
    assert result["retrieval_trace"]["lightrag_enabled"] is False
    assert "neo4j unavailable" in result["retrieval_trace"]["lightrag_error"]
