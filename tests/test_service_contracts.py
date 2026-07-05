from contracts import (
    AnswerContext,
    GraphContext,
    GraphEdge,
    GraphNode,
    RetrievalHit,
    ServiceWarning,
)


def _make_full_hit(
    scores: dict[str, float] | None = None,
) -> RetrievalHit:
    return RetrievalHit(
        rank=1,
        chunk_id="chunk:1:000001",
        doc_id="1",
        title="Luat xay dung",
        document_number="50/2014/QH13",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 89",
        text="Noi dung",
        scores=scores or {"dense": 0.8, "sparse": 12.0, "rrf": 0.03, "rerank": 0.7},
        citation="Luat xay dung, Dieu 89",
    )


# ---------------------------------------------------------------------------
# RetrievalHit
# ---------------------------------------------------------------------------


def test_retrieval_hit_has_all_score_keys() -> None:
    hit = _make_full_hit()
    payload = hit.to_dict()
    assert payload["scores"] == {"dense": 0.8, "sparse": 12.0, "rrf": 0.03, "rerank": 0.7}


def test_retrieval_hit_to_dict_exact_keys() -> None:
    hit = _make_full_hit()
    keys = set(hit.to_dict())
    expected = {
        "rank", "chunk_id", "doc_id", "title", "document_number",
        "legal_type", "effect_status", "section_path", "text",
        "scores", "citation",
    }
    assert keys == expected


def test_retrieval_hit_to_answer_context_maps_all_fields() -> None:
    hit = _make_full_hit()
    ctx = hit.to_answer_context()

    assert ctx.source == "retrieval"
    assert ctx.chunk_id == "chunk:1:000001"
    assert ctx.doc_id == "1"
    assert ctx.title == "Luat xay dung"
    assert ctx.text == "Noi dung"
    assert ctx.citation == "Luat xay dung, Dieu 89"
    # retrieval-origin context inherits no relation or raw_label
    assert ctx.relation is None
    assert ctx.raw_label is None


# ---------------------------------------------------------------------------
# AnswerContext
# ---------------------------------------------------------------------------


def test_answer_context_graph_source_serialization() -> None:
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

    payload = item.to_dict()
    assert payload["source"] == "graph"
    assert payload["relation"] == "CITES"
    assert payload["raw_label"] == "Van ban can cu"


def test_answer_context_to_dict_exact_keys() -> None:
    item = AnswerContext(
        source="graph",
        chunk_id="chunk:2:000001",
        doc_id="2",
        title="Nghi dinh",
        text="Evidence",
        citation="Nghi dinh",
        relation="CITES",
        raw_label="Văn bản căn cứ",
    )
    keys = set(item.to_dict())
    expected = {"source", "chunk_id", "doc_id", "title", "text", "citation", "relation", "raw_label"}
    assert keys == expected


# ---------------------------------------------------------------------------
# GraphEdge  —  raw_label exact preservation with full Vietnamese
# ---------------------------------------------------------------------------


def test_graph_edge_raw_label_preserves_vietnamese_exactly() -> None:
    edge = GraphEdge(
        source="doc:2",
        target="doc:1",
        type="AMENDS",
        raw_label="Văn bản được sửa đổi",
        direction="in",
    )
    payload = edge.to_dict()
    assert payload["raw_label"] == "Văn bản được sửa đổi"


def test_graph_edge_to_dict_exact_keys() -> None:
    edge = GraphEdge(
        source="doc:2",
        target="doc:1",
        type="CITES",
        raw_label="Văn bản dẫn chiếu",
        direction="out",
        properties={"source": "raw"},
    )
    keys = set(edge.to_dict())
    assert keys == {"source", "target", "type", "raw_label", "direction", "properties"}


# ---------------------------------------------------------------------------
# GraphNode
# ---------------------------------------------------------------------------


def test_graph_node_to_dict_exact_keys() -> None:
    node = GraphNode(id="doc:1", label="Document", properties={"doc_id": "1"})
    keys = set(node.to_dict())
    assert keys == {"id", "label", "properties"}


# ---------------------------------------------------------------------------
# GraphContext
# ---------------------------------------------------------------------------


def test_graph_context_empty_center_returns_none() -> None:
    context = GraphContext(center=None)
    payload = context.to_dict()
    assert payload["center"] is None


def test_graph_context_empty_graph_returns_stable_lists() -> None:
    context = GraphContext(center=None)
    payload = context.to_dict()
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert payload["related_chunks"] == []
    assert payload["query_intent"] == "general"


def test_graph_context_to_dict_exact_keys() -> None:
    context = GraphContext(
        center=GraphNode(id="doc:1", label="Document", properties={"doc_id": "1"}),
        nodes=[GraphNode(id="doc:1", label="Document", properties={"doc_id": "1"})],
        edges=[
            GraphEdge(
                source="doc:2",
                target="doc:1",
                type="AMENDS",
                raw_label="Văn bản được sửa đổi",
                direction="in",
            )
        ],
        related_chunks=[],
        query_intent="amendment",
    )

    payload = context.to_dict()
    assert set(payload) == {"center", "nodes", "edges", "related_chunks", "query_intent"}


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


# ---------------------------------------------------------------------------
# ServiceWarning
# ---------------------------------------------------------------------------


def test_service_warning_serializes_code_and_message() -> None:
    warning = ServiceWarning(code="es_unavailable", message="Elasticsearch connection refused")
    payload = warning.to_dict()
    assert payload["code"] == "es_unavailable"
    assert payload["message"] == "Elasticsearch connection refused"
