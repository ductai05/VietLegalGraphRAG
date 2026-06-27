from contracts import (
    AnswerContext,
    GraphContext,
    GraphEdge,
    GraphNode,
    RetrievalHit,
)


def test_retrieval_hit_has_stable_score_keys() -> None:
    hit = RetrievalHit(
        rank=1,
        chunk_id="chunk:1:000001",
        doc_id="1",
        title="Luat xay dung",
        document_number="50/2014/QH13",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 89",
        text="Noi dung",
        scores={"dense": 0.8, "sparse": 12.0, "rrf": 0.03, "rerank": 0.7},
        citation="Luat xay dung, Dieu 89",
    )

    assert hit.to_dict()["scores"]["rrf"] == 0.03
    assert hit.to_answer_context().source == "retrieval"


def test_graph_context_serializes_edges_with_raw_label() -> None:
    context = GraphContext(
        center=GraphNode(id="doc:1", label="Document", properties={"doc_id": "1"}),
        nodes=[GraphNode(id="doc:1", label="Document", properties={"doc_id": "1"})],
        edges=[
            GraphEdge(
                source="doc:2",
                target="doc:1",
                type="AMENDS",
                raw_label="Van ban duoc sua doi",
                direction="in",
            )
        ],
        related_chunks=[],
        query_intent="amendment",
    )

    payload = context.to_dict()
    assert payload["edges"][0]["raw_label"] == "Van ban duoc sua doi"
    assert payload["query_intent"] == "amendment"


def test_answer_context_accepts_graph_source() -> None:
    item = AnswerContext(
        source="graph",
        chunk_id=None,
        doc_id="2",
        title="Nghi dinh",
        text="Graph evidence",
        citation="Nghi dinh",
        relation="CITES",
        raw_label="Van ban can cu",
    )

    assert item.to_dict()["source"] == "graph"
