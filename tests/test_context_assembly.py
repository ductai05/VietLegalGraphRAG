from context_assembler import ContextAssembler
from contracts import AnswerContext, GraphContext, RetrievalHit
from intent_detector import IntentDetector


def test_intent_detector_finds_document_number_and_relation_intent() -> None:
    detected = IntentDetector().detect("Van ban 50/2014/QH13 bi sua doi boi van ban nao?")

    assert detected["document_number"] == "50/2014/QH13"
    assert detected["intent"] == "amendment"


def test_context_assembler_deduplicates_retrieval_and_graph_chunks() -> None:
    retrieval_hit = RetrievalHit(
        rank=1,
        chunk_id="chunk:1:000001",
        doc_id="1",
        title="Doc 1",
        document_number="01/2026/QH",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 1",
        text="Retrieval text",
        scores={},
        citation="Doc 1, Dieu 1",
    )
    graph = GraphContext(
        center=None,
        related_chunks=[
            AnswerContext(
                source="graph",
                chunk_id="chunk:1:000001",
                doc_id="1",
                title="Doc 1",
                text="Graph duplicate",
                citation="Doc 1",
            ),
            AnswerContext(
                source="graph",
                chunk_id="chunk:2:000001",
                doc_id="2",
                title="Doc 2",
                text="Graph new",
                citation="Doc 2",
                relation="AMENDS",
                raw_label="Van ban sua doi",
            ),
        ],
        query_intent="amendment",
    )

    contexts = ContextAssembler().merge([retrieval_hit], graph)

    assert [item.chunk_id for item in contexts] == ["chunk:1:000001", "chunk:2:000001"]
    assert contexts[0].source == "retrieval"
    assert contexts[1].relation == "AMENDS"
