"""Hermetic tests for the DocumentResolver module.

No live Neo4j, Elasticsearch, or LLM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
if str(BACKEND_SERVICES) not in sys.path:
    sys.path.insert(0, str(BACKEND_SERVICES))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_context(
    doc_id: str,
    effect_status: str = "Còn hiệu lực",
    chunk_id: str | None = None,
    source: str = "retrieval",
    title: str = "Test Doc",
    citation: str = "",
) -> Any:
    from contracts import AnswerContext

    return AnswerContext(
        source=source,
        chunk_id=chunk_id or f"chunk:{doc_id}",
        doc_id=doc_id,
        title=title,
        text=f"Content of {doc_id}",
        citation=citation or f"01/2026/QH | {title} | Điều 1 | chunk_id: chunk:{doc_id}",
        effect_status=effect_status,
    )


def _make_graph_context(
    edges: list[tuple[str, str, str]] | None = None,
    related_chunks: list[Any] | None = None,
    nodes: list[tuple[str, dict]] | None = None,
) -> Any:
    from contracts import GraphContext, GraphEdge, GraphNode

    graph_edges = []
    if edges:
        for source, target, edge_type in edges:
            graph_edges.append(
                GraphEdge(
                    source=f"doc:{source}",
                    target=f"doc:{target}",
                    type=edge_type,
                    raw_label=edge_type.lower(),
                    direction="out",
                )
            )

    graph_nodes = []
    if nodes:
        for node_id, properties in nodes:
            graph_nodes.append(
                GraphNode(
                    id=f"doc:{node_id}",
                    label="Document",
                    properties={"doc_id": node_id, **properties},
                )
            )

    return GraphContext(
        center=None,
        nodes=graph_nodes,
        edges=graph_edges,
        related_chunks=related_chunks or [],
        query_intent="general",
    )


# ------------------------------------------------------------------
# DocumentResolver: _is_expired
# ------------------------------------------------------------------

def test_is_expired_detects_expired_statuses() -> None:
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()

    expired_statuses = [
        "Hết hiệu lực",
        "hết hiệu lực",
        "HẾT HIỆU LỰC",
        "het hieu luc",
        "Hết hiệu lực một phần",
        "Ngưng hiệu lực",
    ]
    for status in expired_statuses:
        ctx = _make_context("doc-1", effect_status=status)
        assert resolver._is_expired(ctx), f"Expected expired for status: {status}"


def test_is_expired_returns_false_for_active_statuses() -> None:
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()

    active_statuses = [
        "Còn hiệu lực",
        "con hieu luc",
        "",
        "Chưa có hiệu lực",
    ]
    for status in active_statuses:
        ctx = _make_context("doc-1", effect_status=status)
        assert not resolver._is_expired(ctx), f"Expected active for status: {status}"


# ------------------------------------------------------------------
# DocumentResolver: _build_replacement_map
# ------------------------------------------------------------------

def test_build_replacement_map_from_replaced_by_edge() -> None:
    from document_resolver import DocumentResolver

    graph_context = _make_graph_context(
        edges=[("doc-old", "doc-new", "REPLACED_BY")]
    )
    result = DocumentResolver._build_replacement_map(graph_context)
    assert result == {"doc:doc-old": "doc:doc-new"}


def test_build_replacement_map_from_repeals_edge() -> None:
    from document_resolver import DocumentResolver

    graph_context = _make_graph_context(
        edges=[("doc-new", "doc-old", "REPEALS")]
    )
    result = DocumentResolver._build_replacement_map(graph_context)
    assert result == {"doc:doc-old": "doc:doc-new"}


def test_build_replacement_map_ignores_non_replacement_edges() -> None:
    from document_resolver import DocumentResolver

    graph_context = _make_graph_context(
        edges=[("doc-1", "doc-2", "CITES"), ("doc-1", "doc-3", "AMENDS")]
    )
    result = DocumentResolver._build_replacement_map(graph_context)
    assert result == {}


def test_build_replacement_map_returns_empty_for_none_context() -> None:
    from document_resolver import DocumentResolver

    result = DocumentResolver._build_replacement_map(None)
    assert result == {}


# ------------------------------------------------------------------
# DocumentResolver: resolve — expired document handling
# ------------------------------------------------------------------

def test_resolve_flags_expired_document_with_warning() -> None:
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()
    ctx_expired = _make_context("doc-1", effect_status="Hết hiệu lực")

    result = resolver.resolve([ctx_expired], graph_context=None)

    assert len(result.contexts) == 1
    assert result.contexts[0].resolution is not None
    assert result.contexts[0].resolution["action"] == "expired_warning"
    assert "document.expired:doc-1" in result.warnings


def test_resolve_keeps_active_document_with_kept_action() -> None:
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()
    ctx_active = _make_context("doc-1", effect_status="Còn hiệu lực")

    result = resolver.resolve([ctx_active], graph_context=None)

    assert len(result.contexts) == 1
    assert result.contexts[0].resolution["action"] == "kept"
    assert result.warnings == []


def test_resolve_injects_replacement_for_expired_document() -> None:
    from contracts import AnswerContext
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()
    ctx_expired = _make_context("doc-old", effect_status="Hết hiệu lực")

    replacement_chunk = AnswerContext(
        source="graph",
        chunk_id="chunk:doc-new",
        doc_id="doc-new",
        title="New Doc",
        text="New content",
        citation="02/2026/QH",
        effect_status="Còn hiệu lực",
    )

    graph_context = _make_graph_context(
        edges=[("doc-old", "doc-new", "REPLACED_BY")],
        related_chunks=[replacement_chunk],
        nodes=[("doc-new", {"title": "New Doc", "effect_status": "Còn hiệu lực"})],
    )

    result = resolver.resolve([ctx_expired], graph_context)

    assert len(result.contexts) == 2
    # First is the expired document with replacement annotation.
    assert result.contexts[0].doc_id == "doc-old"
    assert result.contexts[0].resolution["action"] == "replaced"
    assert result.contexts[0].resolution["replacement_doc_id"] == "doc:doc-new"
    # Second is the injected replacement.
    assert result.contexts[1].doc_id == "doc-new"
    assert result.contexts[1].resolution["action"] == "kept"


def test_resolve_mixed_active_and_expired_documents() -> None:
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()
    ctx_active = _make_context("doc-active", effect_status="Còn hiệu lực")
    ctx_expired = _make_context("doc-expired", effect_status="Hết hiệu lực")

    result = resolver.resolve([ctx_active, ctx_expired], graph_context=None)

    assert len(result.contexts) == 2
    assert result.contexts[0].resolution["action"] == "kept"
    assert result.contexts[1].resolution["action"] == "expired_warning"


def test_resolve_does_not_duplicate_replacement_already_in_context() -> None:
    from contracts import AnswerContext
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()
    ctx_expired = _make_context("doc-old", effect_status="Hết hiệu lực")
    ctx_replacement = _make_context("doc-new", effect_status="Còn hiệu lực")

    replacement_chunk = AnswerContext(
        source="graph",
        chunk_id="chunk:doc-new-graph",
        doc_id="doc-new",
        title="New Doc",
        text="New content",
        citation="02/2026/QH",
        effect_status="Còn hiệu lực",
    )

    graph_context = _make_graph_context(
        edges=[("doc-old", "doc-new", "REPLACED_BY")],
        related_chunks=[replacement_chunk],
    )

    # doc-new already appears as an active context.
    result = resolver.resolve([ctx_replacement, ctx_expired], graph_context)

    # Should have 2 contexts: active doc-new (kept) and expired doc-old (replaced).
    doc_ids = [ctx.doc_id for ctx in result.contexts]
    assert doc_ids.count("doc-new") == 1  # No duplicate


# ------------------------------------------------------------------
# DocumentResolver: resolve — version overlap
# ------------------------------------------------------------------

def test_resolve_version_overlap_keeps_newest() -> None:
    from document_resolver import DocumentResolver

    def mock_version_chain(doc_id: str) -> list[dict[str, Any]]:
        return [
            {"doc_id": "doc-v1", "version_order": 0},
            {"doc_id": "doc-v2", "version_order": 1},
        ]

    resolver = DocumentResolver(version_chain_fn=mock_version_chain)
    ctx_v1 = _make_context("doc-v1", citation="01/2026/QH | Old | Điều 1")
    ctx_v2 = _make_context("doc-v2", citation="01/2026/QH | New | Điều 1")

    result = resolver.resolve([ctx_v1, ctx_v2], graph_context=None)

    # Only the newest version should be kept (not superseded).
    kept = [ctx for ctx in result.contexts if ctx.resolution and ctx.resolution["action"] == "kept"]
    superseded = [r for r in result.resolutions if r.action == "superseded"]

    assert len(kept) == 1
    assert kept[0].doc_id == "doc-v2"
    assert len(superseded) == 1
    assert superseded[0].original_doc_id == "doc-v1"


def test_resolve_version_overlap_no_chain_keeps_all() -> None:
    from document_resolver import DocumentResolver

    def mock_version_chain(doc_id: str) -> list[dict[str, Any]]:
        return []

    resolver = DocumentResolver(version_chain_fn=mock_version_chain)
    ctx_v1 = _make_context("doc-v1", citation="01/2026/QH | Old | Điều 1")
    ctx_v2 = _make_context("doc-v2", citation="01/2026/QH | New | Điều 1")

    result = resolver.resolve([ctx_v1, ctx_v2], graph_context=None)

    assert len(result.contexts) == 2


def test_resolve_version_overlap_without_chain_fn_skips() -> None:
    from document_resolver import DocumentResolver

    resolver = DocumentResolver(version_chain_fn=None)
    ctx_v1 = _make_context("doc-v1", citation="01/2026/QH | Old | Điều 1")
    ctx_v2 = _make_context("doc-v2", citation="01/2026/QH | New | Điều 1")

    result = resolver.resolve([ctx_v1, ctx_v2], graph_context=None)

    # Without version_chain_fn, overlap resolution is skipped.
    assert len(result.contexts) == 2


# ------------------------------------------------------------------
# DocumentResolver: resolve — empty input
# ------------------------------------------------------------------

def test_resolve_empty_contexts() -> None:
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()
    result = resolver.resolve([], graph_context=None)

    assert result.contexts == []
    assert result.resolutions == []
    assert result.warnings == []


# ------------------------------------------------------------------
# DocumentResolver: _extract_document_number
# ------------------------------------------------------------------

def test_extract_document_number_from_citation() -> None:
    from document_resolver import DocumentResolver

    ctx = _make_context("doc-1", citation="15/2020/NĐ-CP | Some Title | Điều 1")
    assert DocumentResolver._extract_document_number(ctx) == "15/2020/NĐ-CP"


def test_extract_document_number_empty_citation() -> None:
    from document_resolver import DocumentResolver

    ctx = _make_context("doc-1", citation="")
    assert DocumentResolver._extract_document_number(ctx) == ""


# ------------------------------------------------------------------
# DocumentResolver: _find_replacement_context
# ------------------------------------------------------------------

def test_find_replacement_context_from_related_chunks() -> None:
    from contracts import AnswerContext
    from document_resolver import DocumentResolver

    replacement_chunk = AnswerContext(
        source="graph",
        chunk_id="chunk:doc-new",
        doc_id="doc-new",
        title="New Doc",
        text="New content",
        citation="02/2026/QH",
    )
    graph_context = _make_graph_context(related_chunks=[replacement_chunk])

    result = DocumentResolver._find_replacement_context("doc-new", graph_context)
    assert result is not None
    assert result.doc_id == "doc-new"


def test_find_replacement_context_from_graph_nodes() -> None:
    from document_resolver import DocumentResolver

    graph_context = _make_graph_context(
        nodes=[("doc-new", {"title": "New Doc", "effect_status": "Còn hiệu lực"})],
    )

    result = DocumentResolver._find_replacement_context("doc-new", graph_context)
    assert result is not None
    assert result.doc_id == "doc-new"
    assert result.title == "New Doc"


def test_find_replacement_context_returns_none_when_not_found() -> None:
    from document_resolver import DocumentResolver

    graph_context = _make_graph_context()
    result = DocumentResolver._find_replacement_context("doc-nonexistent", graph_context)
    assert result is None


def test_find_replacement_context_returns_none_for_none_graph() -> None:
    from document_resolver import DocumentResolver

    result = DocumentResolver._find_replacement_context("doc-1", None)
    assert result is None


# ------------------------------------------------------------------
# Integration: ContextAssembler with DocumentResolver
# ------------------------------------------------------------------

def test_context_assembler_with_resolver_annotates_resolution() -> None:
    from context_assembler import ContextAssembler
    from contracts import RetrievalHit
    from document_resolver import DocumentResolver

    resolver = DocumentResolver()
    assembler = ContextAssembler(document_resolver=resolver)

    hits = [
        RetrievalHit(
            rank=1,
            chunk_id="c1",
            doc_id="doc-1",
            title="Doc",
            document_number="01/2026/QH",
            legal_type="Luật",
            effect_status="Còn hiệu lực",
            section_path="Điều 1",
            text="body",
            citation="Doc, Điều 1",
        )
    ]

    result = assembler.merge(hits, graph_context=None)
    assert len(result) == 1
    assert result[0].resolution is not None
    assert result[0].resolution["action"] == "kept"

    # Check last_resolved is populated.
    assert assembler.last_resolved is not None
    assert assembler.last_resolved.warnings == []


def test_context_assembler_without_resolver_returns_plain_contexts() -> None:
    from context_assembler import ContextAssembler
    from contracts import RetrievalHit

    assembler = ContextAssembler(document_resolver=None)

    hits = [
        RetrievalHit(
            rank=1,
            chunk_id="c1",
            doc_id="doc-1",
            title="Doc",
            document_number="01/2026/QH",
            legal_type="Luật",
            effect_status="Còn hiệu lực",
            section_path="Điều 1",
            text="body",
            citation="Doc, Điều 1",
        )
    ]

    result = assembler.merge(hits, graph_context=None)
    assert len(result) == 1
    assert result[0].resolution is None
    assert assembler.last_resolved is None
