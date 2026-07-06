from answer_service import ExtractiveAnswerService
from contracts import AnswerContext


def test_extractive_answer_service_returns_answer_and_citations() -> None:
    service = ExtractiveAnswerService()

    result = service.answer(
        query="q",
        contexts=[
            AnswerContext(
                source="retrieval",
                chunk_id="chunk:1:000001",
                doc_id="1",
                title="Doc 1",
                text="Noi dung tra loi",
                citation="Doc 1, Dieu 1",
            )
        ],
        temperature=0.2,
    )

    assert "Noi dung tra loi" in result["answer"]
    assert result["citations"][0]["chunk_id"] == "chunk:1:000001"
