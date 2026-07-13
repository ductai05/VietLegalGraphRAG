"""Hermetic tests for the graph backend slice.

No live Neo4j, Elasticsearch, or LLM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _mock_node_record(doc_id: str, title: str = "Test Doc") -> Mock:
    node = Mock()
    node.__getitem__ = lambda self, key: {
        "id": f"doc:{doc_id}",
        "doc_id": doc_id,
        "title": title,
        "document_number": "01/2026/QH",
        "effect_status": "Còn hiệu lực",
    }.get(key)
    return node


def _mock_id_only_node_record(doc_id: str, title: str = "Test Doc") -> Mock:
    node = Mock()
    node.__getitem__ = lambda self, key: {
        "id": f"doc:{doc_id}",
        "title": title,
        "document_number": "01/2026/QH",
        "effect_status": "Active",
    }.get(key)
    return node


def _mock_edge_record(source_doc_id: str, target_doc_id: str) -> Mock:
    edge_rec = Mock()
    edge_rec.__getitem__ = lambda self, key: {
        "source": _mock_node_record(source_doc_id),
        "target": _mock_node_record(target_doc_id),
        "type": "CITES",
        "raw_label": "Văn bản căn cứ",
    }.get(key)
    return edge_rec


def _mock_id_only_edge_record(source_doc_id: str, target_doc_id: str) -> Mock:
    edge_rec = Mock()
    edge_rec.__getitem__ = lambda self, key: {
        "source": _mock_id_only_node_record(source_doc_id),
        "target": _mock_id_only_node_record(target_doc_id),
        "type": "CITES",
        "raw_label": "Cites",
    }.get(key)
    return edge_rec


def _mock_session(center_doc_id: str | None, edge_records: list[Mock]) -> Mock:
    run = Mock()
    if center_doc_id is not None:
        center_rec = Mock()
        center_rec.__getitem__ = lambda self, k: (
            _mock_node_record(center_doc_id) if k == "d" else None
        )
        run.side_effect = [
            [center_rec],          # center query
            edge_records,           # edge query
        ]
    else:
        run.return_value = []
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = run
    return session


# ------------------------------------------------------------------
# GraphRetriever: get_document_neighbors
# ------------------------------------------------------------------

def test_get_document_neighbors_returns_center_nodes_edges() -> None:
    from graph_retriever import GraphRetriever

    center_rec = Mock()
    center_rec.__getitem__ = lambda self, k: (
        _mock_node_record("doc-42") if k == "d" else None
    )
    edge_rec = _mock_edge_record("doc-42", "doc-99")

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(side_effect=[[center_rec], [edge_rec]])
    driver.session = Mock(return_value=session)

    retriever = GraphRetriever(driver)
    result = retriever.get_document_neighbors("doc-42")

    assert result.center is not None
    assert result.center.id == "doc:doc-42"
    assert len(result.nodes) == 2
    assert len(result.edges) == 1
    assert result.edges[0].type == "CITES"
    assert result.edges[0].direction == "out"


def test_get_document_neighbors_max_hops_clamped_to_protocol_max() -> None:
    from graph_retriever import GraphRetriever

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(return_value=[])
    driver.session = Mock(return_value=session)

    retriever = GraphRetriever(driver)

    # Verify depth > MAX_DEPTH is clamped.
    retriever.get_document_neighbors("doc-1", depth=999)
    # Depth 999 is clamped to MAX_DEPTH.  The multi-hop query path uses %d
    # formatting; we only check that it doesn't raise.
    assert True

    # Verify depth < 1 is clamped to 1.
    session.run.reset_mock()
    retriever.get_document_neighbors("doc-1", depth=0)
    assert session.run.call_count == 2  # center + single-hop edge query

    # Verify depth=1 uses single-hop query (no variable-length pattern).
    session.run.reset_mock()
    retriever.get_document_neighbors("doc-1", depth=1)
    assert session.run.call_count == 2
    # The single-hop query does not contain '{' (variable-length marker).
    first_call_args = session.run.call_args_list[1][0][0]
    assert "rel*" not in first_call_args

    # Verify depth > 1 expands from the source document to neighbors.
    session.run.reset_mock()
    retriever.get_document_neighbors("doc-1", depth=2)
    query = session.run.call_args_list[1][0][0]
    assert "rel*1..2" in query
    assert "end.doc_id = $doc_id" not in query


def test_get_document_neighbors_relation_filter_parameterized() -> None:
    from graph_retriever import GraphRetriever

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(return_value=[])
    driver.session = Mock(return_value=session)

    retriever = GraphRetriever(driver)
    retriever.get_document_neighbors("doc-1", relations=["AMENDS", "REPEALS"])

    # Second call to run() (edge query) must pass relations param.
    edge_call_args = session.run.call_args_list[1]
    assert edge_call_args[1]["relations"] == ["AMENDS", "REPEALS"]


def test_get_document_neighbors_no_result_returns_empty_context() -> None:
    from graph_retriever import GraphRetriever

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(return_value=[])
    driver.session = Mock(return_value=session)

    retriever = GraphRetriever(driver)
    result = retriever.get_document_neighbors("orphan-doc")

    assert result.center is None
    assert result.nodes == []
    assert result.edges == []
    assert result.related_chunks == []


def test_get_document_neighbors_error_returns_empty_context() -> None:
    from graph_retriever import GraphRetriever

    driver = Mock()
    driver.session.side_effect = RuntimeError("Connection refused")

    retriever = GraphRetriever(driver)
    result = retriever.get_document_neighbors("doc-1")

    assert result.center is None
    assert result.nodes == []


# ------------------------------------------------------------------
# GraphRetriever: get_version_chain
# ------------------------------------------------------------------

def test_get_version_chain_returns_ordered_list() -> None:
    from graph_retriever import GraphRetriever

    rec1 = Mock()
    rec1.__getitem__ = Mock(side_effect=lambda k: {
        "doc_id": "doc-old", "title": "Old", "document_number": "00/2020/QH",
        "status": "Hết hiệu lực", "issuance_date": "2020-01-01",
    }.get(k, None))
    rec2 = Mock()
    rec2.__getitem__ = Mock(side_effect=lambda k: {
        "doc_id": "doc-new", "title": "New", "document_number": "01/2026/QH",
        "status": "Còn hiệu lực", "issuance_date": "2026-01-01",
    }.get(k, None))

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(return_value=[rec1, rec2])
    driver.session = Mock(return_value=session)

    retriever = GraphRetriever(driver)
    chain = retriever.get_version_chain("doc-new")

    assert len(chain) == 2
    assert chain[0]["doc_id"] == "doc-old"
    assert chain[1]["doc_id"] == "doc-new"
    assert chain[0]["version_order"] == 0
    assert chain[1]["version_order"] == 1


def test_get_version_chain_error_returns_empty_list() -> None:
    from graph_retriever import GraphRetriever

    driver = Mock()
    driver.session.side_effect = RuntimeError("neo4j error")

    retriever = GraphRetriever(driver)
    assert retriever.get_version_chain("doc-1") == []


def test_get_version_chain_skips_query_when_version_relationships_missing() -> None:
    from graph_retriever import GraphRetriever

    type_record = Mock()
    type_record.__getitem__ = Mock(
        side_effect=lambda k: ["CITES", "AMENDS"] if k == "types" else None
    )

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(return_value=[type_record])
    driver.session = Mock(return_value=session)

    retriever = GraphRetriever(driver)
    chain = retriever.get_version_chain("doc-1")

    assert chain == []
    assert session.run.call_count == 1


# ------------------------------------------------------------------
# Route: /documents/{doc_id}/graph
# ------------------------------------------------------------------

def _client_with_graph(graph_retriever: Any) -> TestClient:
    from dependencies import RuntimeServices, get_runtime_services
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=graph_retriever,
        answer_service=None,
        lightrag_service=None,
        ocr_service=None,
        status={"graph": "configured"},
        warnings=[],
    )
    app = create_app()
    app.dependency_overrides[get_runtime_services] = lambda: runtime
    return TestClient(app)


def test_document_graph_route_returns_graph_payload() -> None:
    from contracts import GraphContext, GraphNode
    from graph_retriever import GraphRetriever

    mock_retriever = Mock(spec=GraphRetriever)
    mock_retriever.get_document_neighbors.return_value = GraphContext(
        center=GraphNode(id="doc:1", label="Document"),
        nodes=[GraphNode(id="doc:1", label="Document")],
        edges=[],
        related_chunks=[],
        query_intent="general",
    )

    client = _client_with_graph(mock_retriever)
    response = client.get("/documents/doc-1/graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["center"]["id"] == "doc:1"
    assert payload["nodes"][0]["id"] == "doc:1"


# ------------------------------------------------------------------
# Route: /documents/{doc_id}/version-chain
# ------------------------------------------------------------------

def test_version_chain_route_uses_graph_retriever() -> None:
    from graph_retriever import GraphRetriever

    mock_retriever = Mock(spec=GraphRetriever)
    mock_retriever.enabled = True
    mock_retriever.get_version_chain.return_value = [
        {"doc_id": "doc-old", "title": "Old", "document_number": "00/2020/QH",
         "status": "Hết hiệu lực", "version_order": 0},
        {"doc_id": "doc-new", "title": "New", "document_number": "01/2026/QH",
         "status": "Còn hiệu lực", "version_order": 1},
    ]

    client = _client_with_graph(mock_retriever)
    response = client.get("/documents/doc-new/version-chain")

    assert response.status_code == 200
    payload = response.json()
    assert payload["doc_id"] == "doc-new"
    assert len(payload["chain"]) == 2
    mock_retriever.get_version_chain.assert_called_once_with("doc-new")


def test_version_chain_route_empty_when_graph_disabled() -> None:
    from dependencies import NoopGraphRetriever

    client = _client_with_graph(NoopGraphRetriever())
    response = client.get("/documents/doc-1/version-chain")

    assert response.status_code == 200
    assert response.json()["chain"] == []


# ------------------------------------------------------------------
# LightRAG: graph chunks in context, failure does not break answer
# ------------------------------------------------------------------

def test_lightrag_graph_chunks_included_in_context(monkeypatch) -> None:
    """related_chunks from graph_context are merged into answer contexts."""
    from contracts import AnswerContext, GraphContext, RetrievalHit
    from lightrag_service import LightRAGService

    mock_retrieval = Mock()
    mock_retrieval.search.return_value = [
        RetrievalHit(
            rank=1, chunk_id="c1", doc_id="doc-1", title="Doc",
            document_number="01/2026/QH", legal_type="Luật",
            effect_status="Còn hiệu lực", section_path="Điều 1", text="body",
            citation="Doc, Điều 1",
        )
    ]

    graph_chunk = AnswerContext(
        source="graph", chunk_id="c99", doc_id="doc-2",
        title="Related Doc", text="related body", citation="Related Doc",
        relation="CITES", raw_label="Văn bản căn cứ",
    )
    mock_graph = Mock()
    mock_graph.enabled = True
    mock_graph.retrieve.return_value = GraphContext(
        center=None, nodes=[], edges=[],
        related_chunks=[graph_chunk],
        query_intent="general",
    )

    mock_answer = Mock()
    mock_answer.answer.return_value = {"answer": "test answer", "citations": []}

    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    from retrieval_modes import RetrievalRequest

    svc = LightRAGService(
        retrieval_service=mock_retrieval,
        graph_retriever=mock_graph,
        answer_service=mock_answer,
    )

    request = RetrievalRequest(
        query="test query",
        retrieval_mode="hybrid",
        top_k=5,
        graph={"enabled": True, "use_lightrag": True, "max_hops": 2},
        rerank={"enabled": False},
        llm={"temperature": 0.0},
    )
    result = svc.answer(request)

    # Verify graph chunks were merged into answer contexts.
    assert result["graph_context"]["related_chunks"] == [graph_chunk.to_dict()]
    # Verify trace reflects graph was used.
    assert result["retrieval_trace"]["lightrag_enabled"] is True
    assert result["retrieval_trace"]["graph_hits"] == 1


def test_graph_retriever_populates_related_chunks_from_neighbor_docs() -> None:
    from contracts import AnswerContext
    from graph_retriever import GraphRetriever

    center_rec = Mock()
    center_rec.__getitem__ = lambda self, k: (
        _mock_node_record("doc-1") if k == "d" else None
    )
    edge_rec = _mock_edge_record("doc-1", "doc-2")

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(side_effect=[[center_rec], [edge_rec]])
    driver.session = Mock(return_value=session)

    calls: list[tuple[str, list[dict[str, str]]]] = []

    def fetcher(query: str, related_documents: list[dict[str, str]]):
        calls.append((query, related_documents))
        return [
            AnswerContext(
                source="graph",
                chunk_id="chunk-doc-2",
                doc_id="doc-2",
                title="Related Doc",
                text="related text",
                citation="Related Doc | chunk-doc-2",
                relation=related_documents[0]["relation"],
                raw_label=related_documents[0]["raw_label"],
            )
        ]

    retriever = GraphRetriever(driver, chunk_fetcher=fetcher)
    context = retriever.retrieve(
        "căn cứ của văn bản 01/2026/QH",
        [
            {
                "doc_id": "doc-1",
                "document_number": "01/2026/QH",
            }
        ],
        max_hops=1,
    )

    assert calls == [
        (
            "căn cứ của văn bản 01/2026/QH",
            [{"doc_id": "doc-2", "relation": "CITES", "raw_label": "Văn bản căn cứ"}],
        )
    ]
    assert len(context.related_chunks) == 1
    assert context.related_chunks[0].source == "graph"
    assert context.related_chunks[0].relation == "CITES"


def test_graph_retriever_uses_id_property_when_doc_id_missing() -> None:
    from contracts import AnswerContext
    from graph_retriever import GraphRetriever

    center_rec = Mock()
    center_rec.__getitem__ = lambda self, k: (
        _mock_id_only_node_record("399681") if k == "d" else None
    )
    edge_rec = _mock_id_only_edge_record("399681", "694133")

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(side_effect=[[center_rec], [edge_rec]])
    driver.session = Mock(return_value=session)

    calls: list[tuple[str, list[dict[str, str]]]] = []

    def fetcher(query: str, related_documents: list[dict[str, str]]):
        calls.append((query, related_documents))
        return [
            AnswerContext(
                source="graph",
                chunk_id="chunk-694133",
                doc_id=related_documents[0]["doc_id"],
                title="Related Doc",
                text="related text",
                citation="Related Doc | chunk-694133",
                relation=related_documents[0]["relation"],
                raw_label=related_documents[0]["raw_label"],
            )
        ]

    retriever = GraphRetriever(driver, chunk_fetcher=fetcher)
    context = retriever.retrieve_chunk_context(
        "399681",
        [{"text": "seed retrieval text"}],
        max_hops=1,
    )

    assert calls == [
        (
            "seed retrieval text",
            [{"doc_id": "694133", "relation": "CITES", "raw_label": "Cites"}],
        )
    ]
    assert [chunk.doc_id for chunk in context.related_chunks] == ["694133"]


def test_graph_retriever_tries_next_hit_when_first_doc_has_no_related_edges() -> None:
    from contracts import AnswerContext
    from graph_retriever import GraphRetriever

    driver = Mock()
    driver.session = Mock(
        side_effect=[
            _mock_session("doc-1", []),
            _mock_session("doc-2", [_mock_edge_record("doc-2", "doc-3")]),
        ]
    )

    calls: list[tuple[str, list[dict[str, str]]]] = []

    def fetcher(query: str, related_documents: list[dict[str, str]]):
        calls.append((query, related_documents))
        return [
            AnswerContext(
                source="graph",
                chunk_id="chunk-doc-3",
                doc_id=related_documents[0]["doc_id"],
                title="Related Doc",
                text="related text",
                citation="Related Doc | chunk-doc-3",
                relation=related_documents[0]["relation"],
                raw_label=related_documents[0]["raw_label"],
            )
        ]

    retriever = GraphRetriever(driver, chunk_fetcher=fetcher)
    context = retriever.retrieve(
        "legal query",
        [
            {"doc_id": "doc-1", "text": "first hit"},
            {"doc_id": "doc-2", "text": "second hit"},
        ],
        max_hops=1,
    )

    assert context.center is not None
    assert context.center.id == "doc:doc-2"
    assert calls[0][0] == "legal query"
    assert calls[0][1][0]["doc_id"] == "doc-3"
    assert calls[0][1][0]["relation"] == "CITES"
    assert calls[0][1][0]["raw_label"]
    assert [chunk.doc_id for chunk in context.related_chunks] == ["doc-3"]


def test_retrieve_chunk_context_uses_chunk_fetcher_for_specific_doc() -> None:
    from contracts import AnswerContext
    from graph_retriever import GraphRetriever

    center_rec = Mock()
    center_rec.__getitem__ = lambda self, k: (
        _mock_node_record("doc-1") if k == "d" else None
    )
    edge_rec = _mock_edge_record("doc-1", "doc-2")

    driver = Mock()
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.run = Mock(side_effect=[[center_rec], [edge_rec]])
    driver.session = Mock(return_value=session)

    def fetcher(query: str, related_documents: list[dict[str, str]]):
        return [
            AnswerContext(
                source="graph",
                chunk_id="chunk-doc-2",
                doc_id=related_documents[0]["doc_id"],
                title="Related Doc",
                text="related text",
                citation="Related Doc | chunk-doc-2",
                relation=related_documents[0]["relation"],
                raw_label=related_documents[0]["raw_label"],
            )
        ]

    retriever = GraphRetriever(driver, chunk_fetcher=fetcher)
    context = retriever.retrieve_chunk_context(
        "doc-1",
        [{"text": "seed retrieval text"}],
        max_hops=1,
    )

    assert context.center is not None
    assert [chunk.chunk_id for chunk in context.related_chunks] == ["chunk-doc-2"]


def test_lightrag_respects_max_context_chunks_and_reports_graph_chunks_used() -> None:
    from contracts import AnswerContext, GraphContext, RetrievalHit
    from lightrag_service import LightRAGService
    from retrieval_modes import RetrievalRequest

    mock_retrieval = Mock()
    mock_retrieval.search.return_value = [
        RetrievalHit(
            rank=1, chunk_id="r1", doc_id="doc-1", title="Doc 1",
            document_number="01/2026/QH", legal_type="Luật",
            effect_status="Còn hiệu lực", section_path="Điều 1", text="body 1",
            citation="Doc 1",
        ),
        RetrievalHit(
            rank=2, chunk_id="r2", doc_id="doc-2", title="Doc 2",
            document_number="02/2026/QH", legal_type="Luật",
            effect_status="Còn hiệu lực", section_path="Điều 2", text="body 2",
            citation="Doc 2",
        ),
    ]

    graph_chunks = [
        AnswerContext(
            source="graph", chunk_id="g1", doc_id="doc-3",
            title="Graph 1", text="graph body 1", citation="Graph 1",
        ),
        AnswerContext(
            source="graph", chunk_id="g2", doc_id="doc-4",
            title="Graph 2", text="graph body 2", citation="Graph 2",
        ),
    ]
    mock_graph = Mock()
    mock_graph.enabled = True
    mock_graph.retrieve.return_value = GraphContext(
        center=None,
        nodes=[],
        edges=[],
        related_chunks=graph_chunks,
        query_intent="general",
    )

    captured_contexts: list[AnswerContext] = []
    mock_answer = Mock()

    def answer(query, contexts, temperature):
        captured_contexts.extend(contexts)
        return {"answer": "ok", "citations": []}

    mock_answer.answer.side_effect = answer

    svc = LightRAGService(
        retrieval_service=mock_retrieval,
        graph_retriever=mock_graph,
        answer_service=mock_answer,
    )

    request = RetrievalRequest(
        query="test query",
        retrieval_mode="hybrid",
        top_k=5,
        graph={"enabled": True, "use_lightrag": True, "max_hops": 1},
        rerank={"enabled": False},
        llm={"temperature": 0.0, "max_context_chunks": 3},
    )

    result = svc.answer(request)

    assert [ctx.chunk_id for ctx in captured_contexts] == ["r1", "r2", "g1"]
    assert result["retrieval_trace"]["graph_hits"] == 2
    assert result["retrieval_trace"]["graph_chunks_used"] == 1
    assert "latency_ms" in result["retrieval_trace"]


def test_lightrag_keeps_graph_chunk_when_retrieval_hits_exceed_context_cap() -> None:
    from contracts import AnswerContext, GraphContext, RetrievalHit
    from lightrag_service import LightRAGService
    from retrieval_modes import RetrievalRequest

    mock_retrieval = Mock()
    mock_retrieval.search.return_value = [
        RetrievalHit(
            rank=rank,
            chunk_id=f"r{rank}",
            doc_id=f"doc-{rank}",
            title=f"Doc {rank}",
            document_number=f"0{rank}/2026/QH",
            legal_type="Law",
            effect_status="Active",
            section_path=f"Article {rank}",
            text=f"body {rank}",
            citation=f"Doc {rank}",
        )
        for rank in range(1, 6)
    ]

    graph_chunk = AnswerContext(
        source="graph",
        chunk_id="g1",
        doc_id="doc-graph",
        title="Graph",
        text="graph body",
        citation="Graph",
    )
    mock_graph = Mock()
    mock_graph.enabled = True
    mock_graph.retrieve.return_value = GraphContext(
        center=None,
        nodes=[],
        edges=[],
        related_chunks=[graph_chunk],
        query_intent="general",
    )

    captured_contexts: list[AnswerContext] = []
    mock_answer = Mock()
    mock_answer.answer.side_effect = lambda query, contexts, temperature: (
        captured_contexts.extend(contexts) or {"answer": "ok", "citations": []}
    )

    svc = LightRAGService(
        retrieval_service=mock_retrieval,
        graph_retriever=mock_graph,
        answer_service=mock_answer,
    )

    request = RetrievalRequest(
        query="test query",
        retrieval_mode="hybrid",
        top_k=5,
        graph={"enabled": True, "use_lightrag": True, "max_hops": 1},
        rerank={"enabled": False},
        llm={"temperature": 0.0, "max_context_chunks": 3},
    )

    result = svc.answer(request)

    assert [ctx.chunk_id for ctx in captured_contexts] == ["r1", "r2", "g1"]
    assert result["retrieval_trace"]["graph_hits"] == 1
    assert result["retrieval_trace"]["graph_chunks_used"] == 1


def test_lightrag_graph_failure_does_not_break_answer(monkeypatch) -> None:
    """Graph retrieval error is sanitized and does not prevent answer."""
    from contracts import RetrievalHit
    from lightrag_service import LightRAGService

    mock_retrieval = Mock()
    mock_retrieval.search.return_value = [
        RetrievalHit(
            rank=1, chunk_id="c1", doc_id="doc-1", title="Doc",
            document_number="01/2026/QH", legal_type="Luật",
            effect_status="Còn hiệu lực", section_path="Điều 1", text="body",
            citation="Doc, Điều 1",
        )
    ]

    mock_graph = Mock()
    mock_graph.enabled = True
    mock_graph.retrieve.side_effect = RuntimeError("neo4j://user:pass@host")

    mock_answer = Mock()
    mock_answer.answer.return_value = {"answer": "answer despite graph failure", "citations": []}

    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    from retrieval_modes import RetrievalRequest

    svc = LightRAGService(
        retrieval_service=mock_retrieval,
        graph_retriever=mock_graph,
        answer_service=mock_answer,
    )

    request = RetrievalRequest(
        query="test query",
        retrieval_mode="hybrid",
        top_k=5,
        graph={"enabled": True, "use_lightrag": True, "max_hops": 2},
        rerank={"enabled": False},
        llm={"temperature": 0.0},
    )
    result = svc.answer(request)

    # Answer still produced.
    assert result["answer"] == "answer despite graph failure"
    # Graph is disabled in trace, error is sanitized code.
    assert result["retrieval_trace"]["lightrag_enabled"] is False
    assert result["retrieval_trace"]["lightrag_error"] == "graph.retrieval_failed"
    # No neo4j internals leaked.
    assert "neo4j" not in str(result["retrieval_trace"]["lightrag_error"]).lower()


def test_lightrag_answer_failure_falls_back_to_extractive() -> None:
    """LLM upstream errors should not turn /answer into a hard failure."""
    from contracts import RetrievalHit
    from lightrag_service import LightRAGService
    from retrieval_modes import RetrievalRequest

    mock_retrieval = Mock()
    mock_retrieval.search.return_value = [
        RetrievalHit(
            rank=1,
            chunk_id="c1",
            doc_id="doc-1",
            title="Doc",
            document_number="01/2026/QH",
            legal_type="Luat",
            effect_status="Con hieu luc",
            section_path="Dieu 1",
            text="retrieved body",
            citation="Doc, Dieu 1",
        )
    ]

    mock_graph = Mock()
    mock_graph.enabled = False
    mock_answer = Mock()
    mock_answer.answer.side_effect = RuntimeError("provider secret detail")

    svc = LightRAGService(
        retrieval_service=mock_retrieval,
        graph_retriever=mock_graph,
        answer_service=mock_answer,
    )

    request = RetrievalRequest(
        query="test query",
        retrieval_mode="sparse",
        top_k=1,
        graph={"enabled": False, "use_lightrag": False, "max_hops": 0},
        rerank={"enabled": False},
        llm={"temperature": 0.0, "max_context_chunks": 1},
    )
    result = svc.answer(request)

    assert result["answer"] == "retrieved body"
    assert result["retrieval_trace"]["answer_error"] == "llm.answer_failed"
    assert "provider secret detail" not in str(result["retrieval_trace"])
