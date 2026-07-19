"""Hermetic tests for the LangGraph ReAct agent tools and AgentService.

No live Elasticsearch, Neo4j, LLM, or Exa calls. The compiled LangGraph is
stubbed out so these cover our own orchestration logic, not LangGraph's.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICES = ROOT / "src" / "vietlegal_rag" / "services"
if str(RAG_SERVICES) not in sys.path:
    sys.path.insert(0, str(RAG_SERVICES))

pytest.importorskip("langgraph.prebuilt")
pytest.importorskip("langchain_core.tools")


# ----------------------------------------------------------------------
# Fixtures / fakes
# ----------------------------------------------------------------------


def _hit(
    doc_id: str = "nd15",
    chunk_id: str = "chunk:nd15:000101",
    effect_status: str = "Còn hiệu lực",
    section_path: str = "Điều 101",
) -> Any:
    from contracts import RetrievalHit

    title = "Nghị định 15/2020/NĐ-CP quy định xử phạt vi phạm hành chính"
    return RetrievalHit(
        rank=1,
        chunk_id=chunk_id,
        doc_id=doc_id,
        title=title,
        document_number="15/2020/NĐ-CP",
        legal_type="Nghị định",
        effect_status=effect_status,
        section_path=section_path,
        text="Nội dung điều luật." * 200,
        scores={"hybrid": 1.0},
        citation=f"15/2020/NĐ-CP | {title} | {section_path} | chunk_id: {chunk_id}",
    )


def _request(query: str = "xử phạt vi phạm hành chính") -> Any:
    from retrieval_modes import RetrievalRequest

    return RetrievalRequest(query=query, top_k=5)


class _FakeRetrievalService:
    def __init__(self, hits: list[Any] | None = None, error: Exception | None = None) -> None:
        self.hits = hits if hits is not None else [_hit()]
        self.error = error
        self.requests: list[Any] = []

    def search(self, request: Any) -> list[Any]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.hits


class _FakeGraphRetriever:
    """Mirrors NoopGraphRetriever's surface with configurable output."""

    enabled = True

    def __init__(self, context: Any = None, error: Exception | None = None) -> None:
        self.context = context
        self.error = error

    def _result(self) -> Any:
        from contracts import GraphContext

        if self.error is not None:
            raise self.error
        return self.context if self.context is not None else GraphContext(center=None)

    def retrieve(self, query, retrieval_hits, max_hops, auto_depth=True):
        return self._result()

    def get_document_neighbors(self, doc_id, relations=None, depth=1):
        return self._result()

    def get_version_chain(self, doc_id):
        return []


def _graph_context(center_id: str | None = "doc:nd15", edges: list[Any] | None = None) -> Any:
    from contracts import GraphContext, GraphNode

    center = (
        GraphNode(id=center_id, label="Document", properties={"doc_id": center_id})
        if center_id
        else None
    )
    return GraphContext(center=center, nodes=[], edges=edges or [], related_chunks=[])


class _StubResolver:
    """Returns contexts carrying preset resolution dicts, to pin the
    action -> effect_verdict mapping without staging the real resolver."""

    def __init__(self, resolutions: list[dict[str, Any]]) -> None:
        self.resolutions = resolutions

    def resolve(self, contexts: list[Any], graph_context: Any) -> Any:
        from document_resolver import ResolvedResult

        for context, resolution in zip(contexts, self.resolutions):
            context.resolution = resolution
        return ResolvedResult(contexts=contexts, resolutions=[], warnings=[])


# ----------------------------------------------------------------------
# Tool 1 — retrieval_search
# ----------------------------------------------------------------------


def test_retrieval_tool_returns_json_and_collects_hits() -> None:
    from agent_tools import AgentRunState, make_retrieval_tool

    state = AgentRunState()
    tool = make_retrieval_tool(_FakeRetrievalService(), _request(), state)

    payload = json.loads(tool.invoke({"query": "xử phạt", "top_k": 3}))

    assert payload[0]["doc_id"] == "nd15"
    assert payload[0]["section_path"] == "Điều 101"
    assert len(state.hits) == 1
    assert state.tools_used == ["retrieval_search"]
    assert state.tool_calls == 1


def test_retrieval_tool_truncates_text_to_protect_context_window() -> None:
    from agent_tools import MAX_TOOL_TEXT_CHARS, AgentRunState, make_retrieval_tool

    state = AgentRunState()
    tool = make_retrieval_tool(_FakeRetrievalService(), _request(), state)

    payload = json.loads(tool.invoke({"query": "xử phạt"}))

    assert len(payload[0]["text"]) == MAX_TOOL_TEXT_CHARS


def test_retrieval_tool_clamps_top_k_to_candidate_k_instead_of_raising() -> None:
    from agent_tools import AgentRunState, make_retrieval_tool

    base = _request()
    base.rerank.enabled = True
    base.rerank.candidate_k = 6
    service = _FakeRetrievalService()
    tool = make_retrieval_tool(service, base, AgentRunState())

    tool.invoke({"query": "xử phạt", "top_k": 20})

    # dataclasses.replace re-runs __post_init__, which rejects top_k > candidate_k.
    assert service.requests[0].top_k == 6


def test_retrieval_tool_returns_error_json_instead_of_raising() -> None:
    from agent_tools import AgentRunState, make_retrieval_tool

    service = _FakeRetrievalService(error=RuntimeError("elasticsearch down"))
    tool = make_retrieval_tool(service, _request(), AgentRunState())

    assert json.loads(tool.invoke({"query": "xử phạt"})) == {"error": "retrieval_failed"}


def test_retrieval_tool_dedupes_hits_across_calls() -> None:
    from agent_tools import AgentRunState, make_retrieval_tool

    state = AgentRunState()
    tool = make_retrieval_tool(_FakeRetrievalService(), _request(), state)

    tool.invoke({"query": "xử phạt"})
    tool.invoke({"query": "xử phạt lần hai"})

    assert len(state.hits) == 1


# ----------------------------------------------------------------------
# Tool 2 — graph_validate verdict mapping
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "action, expected_verdict",
    [
        ("kept", "in_force"),
        ("replaced", "expired"),
        ("expired_warning", "expired"),
        ("superseded", "superseded"),
    ],
)
def test_graph_validate_maps_each_resolution_action(action: str, expected_verdict: str) -> None:
    from agent_tools import AgentRunState, make_graph_validate_tool

    state = AgentRunState()
    state.hits = [_hit()]
    resolver = _StubResolver([{"action": action, "reason": "lý do", "replacement_doc_id": "nd50"}])
    tool = make_graph_validate_tool(_FakeGraphRetriever(_graph_context()), resolver, state)

    payload = json.loads(tool.invoke({"doc_ids": ["nd15"]}))[0]

    assert payload["effect_verdict"] == expected_verdict
    assert payload["available"] is True
    assert payload["reason"] == "lý do"
    assert state.graph_validation == "agent_tool"


def test_graph_validate_takes_most_severe_verdict_on_disagreement() -> None:
    from agent_tools import AgentRunState, make_graph_validate_tool

    state = AgentRunState()
    state.hits = [_hit(chunk_id="chunk:nd15:1"), _hit(chunk_id="chunk:nd15:2")]
    resolver = _StubResolver(
        [
            {"action": "kept", "reason": "còn hiệu lực"},
            {"action": "expired_warning", "reason": "hết hiệu lực"},
        ]
    )
    tool = make_graph_validate_tool(_FakeGraphRetriever(_graph_context()), resolver, state)

    payload = json.loads(tool.invoke({"doc_ids": ["nd15"]}))[0]

    assert payload["effect_verdict"] == "expired"


def test_graph_validate_downgrades_in_force_to_unknown_without_a_graph() -> None:
    from agent_tools import AgentRunState, make_graph_validate_tool

    state = AgentRunState()
    state.hits = [_hit()]
    resolver = _StubResolver([{"action": "kept", "reason": "Tài liệu còn hiệu lực"}])
    # center is None: NoopGraphRetriever's degradation path.
    tool = make_graph_validate_tool(_FakeGraphRetriever(_graph_context(center_id=None)), resolver, state)

    payload = json.loads(tool.invoke({"doc_ids": ["nd15"]}))[0]

    assert payload["available"] is False
    assert payload["effect_verdict"] == "unknown"


def test_graph_validate_returns_unknown_when_no_context_matches() -> None:
    from agent_tools import AgentRunState, make_graph_validate_tool
    from document_resolver import DocumentResolver

    state = AgentRunState()
    state.hits = [_hit(doc_id="other")]
    tool = make_graph_validate_tool(
        _FakeGraphRetriever(_graph_context()), DocumentResolver(), state
    )

    payload = json.loads(tool.invoke({"doc_ids": ["nd15"]}))[0]

    assert payload["effect_verdict"] == "unknown"


def test_graph_validate_matches_doc_id_ignoring_the_doc_prefix() -> None:
    from agent_tools import AgentRunState, make_graph_validate_tool
    from document_resolver import DocumentResolver

    state = AgentRunState()
    state.hits = [_hit(doc_id="nd15")]
    tool = make_graph_validate_tool(
        _FakeGraphRetriever(_graph_context()), DocumentResolver(), state
    )

    payload = json.loads(tool.invoke({"doc_ids": ["doc:nd15"]}))[0]

    assert payload["effect_verdict"] == "in_force"


def test_graph_validate_uses_real_resolver_for_expired_status() -> None:
    from agent_tools import AgentRunState, make_graph_validate_tool
    from document_resolver import DocumentResolver

    state = AgentRunState()
    state.hits = [_hit(effect_status="Hết hiệu lực")]
    tool = make_graph_validate_tool(
        _FakeGraphRetriever(_graph_context()), DocumentResolver(), state
    )

    payload = json.loads(tool.invoke({"doc_ids": ["nd15"]}))[0]

    assert payload["effect_verdict"] == "expired"
    # The resolver's own Vietnamese wording is passed through verbatim.
    assert payload["reason"] == "Tài liệu đã hết hiệu lực, không tìm thấy tài liệu thay thế"


def test_graph_validate_never_raises_when_the_graph_errors() -> None:
    from agent_tools import AgentRunState, make_graph_validate_tool
    from document_resolver import DocumentResolver

    tool = make_graph_validate_tool(
        _FakeGraphRetriever(error=RuntimeError("neo4j down")),
        DocumentResolver(),
        AgentRunState(),
    )

    payload = json.loads(tool.invoke({"doc_ids": ["nd15"]}))[0]

    assert payload["effect_verdict"] == "unknown"
    assert payload["available"] is False


def test_graph_validate_batches_multiple_doc_ids_in_one_call() -> None:
    from agent_tools import AgentRunState, make_graph_validate_tool
    from document_resolver import DocumentResolver

    state = AgentRunState()
    state.hits = [
        _hit(doc_id="nd15", chunk_id="chunk:nd15:1"),
        _hit(doc_id="nd50", chunk_id="chunk:nd50:1"),
    ]
    tool = make_graph_validate_tool(
        _FakeGraphRetriever(_graph_context()), DocumentResolver(), state
    )

    payload = json.loads(tool.invoke({"doc_ids": ["nd15", "nd50", "nd15"]}))

    # One tool step validates every (deduplicated) doc_id.
    assert [entry["doc_id"] for entry in payload] == ["nd15", "nd50"]
    assert state.tool_calls == 1


# ----------------------------------------------------------------------
# Tool 3 — web_find_source_link
# ----------------------------------------------------------------------


def test_web_tool_returns_results_and_records_the_link() -> None:
    from agent_tools import AgentRunState, make_web_search_tool
    from web_search_service import NoopWebSearch

    class _Search(NoopWebSearch):
        def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
            self.query = query
            return [{"title": "t", "url": "https://vbpl.vn/nd15", "snippet": "s", "provider": "exa"}]

    state = AgentRunState()
    search = _Search()
    tool = make_web_search_tool(search, state)

    payload = json.loads(tool.invoke({"document_title": "Nghị định 15/2020/NĐ-CP quy định xử phạt"}))

    assert payload[0]["url"] == "https://vbpl.vn/nd15"
    assert state.links == {"Nghị định 15/2020/NĐ-CP": "https://vbpl.vn/nd15"}
    assert search.query == "Nghị định 15/2020/NĐ-CP toàn văn"


def test_web_tool_returns_empty_list_when_no_provider_configured() -> None:
    from agent_tools import AgentRunState, make_web_search_tool
    from web_search_service import NoopWebSearch

    tool = make_web_search_tool(NoopWebSearch(), AgentRunState())

    assert json.loads(tool.invoke({"document_title": "Nghị định 15/2020/NĐ-CP"})) == []


def test_web_tool_returns_empty_list_instead_of_raising() -> None:
    from agent_tools import AgentRunState, make_web_search_tool

    class _Broken:
        def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
            raise RuntimeError("exa down")

    tool = make_web_search_tool(_Broken(), AgentRunState())

    assert json.loads(tool.invoke({"document_title": "Nghị định 15/2020/NĐ-CP"})) == []


# ----------------------------------------------------------------------
# AgentService
# ----------------------------------------------------------------------


class _FakeCompiledGraph:
    def __init__(self, events: list[Any] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error

    def stream(self, inputs: Any, config: Any = None, stream_mode: Any = None) -> Any:
        if self.error is not None:
            raise self.error
        yield from self.events


class _FakeLightRAGService:
    def __init__(self) -> None:
        self.calls = 0

    def stream_answer(self, request: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "answer_stream": iter(["Câu trả lời tĩnh."]),
            "citations": [{"chunk_id": "c1", "doc_id": "d1", "title": "T", "citation": "C"}],
            "retrieval_context": [{"doc_id": "d1"}],
            "graph_context": {"center": None},
            "retrieval_trace": {"retrieval_mode": "hybrid"},
        }


def _text_event(text: str) -> tuple[str, tuple[Any, dict[str, Any]]]:
    from langchain_core.messages import AIMessageChunk

    return ("messages", (AIMessageChunk(content=text), {}))


def _build_service(**overrides: Any) -> Any:
    from agent_service import AgentService
    from document_resolver import DocumentResolver

    kwargs: dict[str, Any] = {
        "retrieval_service": _FakeRetrievalService(),
        "graph_retriever": _FakeGraphRetriever(),
        "document_resolver": DocumentResolver(),
        "web_search": None,
        "llm": object(),
        "fallback_service": _FakeLightRAGService(),
    }
    kwargs.update(overrides)
    return AgentService(**kwargs)


def _patch_graph(
    monkeypatch: Any,
    service: Any,
    graph: Any,
    seed_hits: list[Any] | None = None,
) -> None:
    """Bypass create_react_agent; optionally seed the per-request state the
    real tools would have filled."""

    def _fake_build(request: Any, state: Any) -> Any:
        if seed_hits is not None:
            state.hits.extend(seed_hits)
        return graph

    monkeypatch.setattr(service, "_build_graph", _fake_build)


def test_stream_answer_yields_answer_text_and_builds_citations(monkeypatch: Any) -> None:
    service = _build_service()
    _patch_graph(
        monkeypatch,
        service,
        _FakeCompiledGraph([_text_event("Theo "), _text_event("quy định...")]),
        seed_hits=[_hit()],
    )

    result = service.stream_answer(_request())
    tokens = list(result["answer_stream"])

    assert "".join(tokens).startswith("Theo quy định...")
    assert result["citations"][0]["doc_id"] == "nd15"
    assert result["retrieval_trace"]["mode"] == "agent"


def test_stream_answer_falls_back_when_the_llm_raises_on_the_first_token(
    monkeypatch: Any,
) -> None:
    fallback = _FakeLightRAGService()
    service = _build_service(fallback_service=fallback)
    _patch_graph(monkeypatch, service, _FakeCompiledGraph(error=RuntimeError("llm down")))

    result = service.stream_answer(_request())
    tokens = list(result["answer_stream"])

    assert "".join(tokens) == "Câu trả lời tĩnh."
    assert fallback.calls == 1
    assert result["retrieval_trace"]["agent_error"] == "agent.stream_failed"
    assert result["citations"][0]["citation"] == "C"


def test_stream_answer_falls_back_when_the_agent_produces_no_answer(monkeypatch: Any) -> None:
    fallback = _FakeLightRAGService()
    service = _build_service(fallback_service=fallback)
    _patch_graph(monkeypatch, service, _FakeCompiledGraph([]))

    list(service.stream_answer(_request())["answer_stream"])

    assert fallback.calls == 1


def test_stream_answer_does_not_yield_tool_call_chunks_as_answer_text(
    monkeypatch: Any,
) -> None:
    from langchain_core.messages import AIMessageChunk

    tool_chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": "retrieval_search", "args": '{"query":"x"}', "id": "1", "index": 0}
        ],
    )
    service = _build_service()
    _patch_graph(
        monkeypatch,
        service,
        _FakeCompiledGraph([("messages", (tool_chunk, {})), _text_event("Trả lời.")]),
        seed_hits=[_hit()],
    )

    tokens = list(service.stream_answer(_request())["answer_stream"])

    assert "".join(tokens) == "Trả lời."


def test_stream_answer_wraps_reasoning_content_in_think_tags(monkeypatch: Any) -> None:
    from langchain_core.messages import AIMessageChunk

    reasoning_chunk = AIMessageChunk(
        content="", additional_kwargs={"reasoning_content": "đang suy nghĩ"}
    )
    service = _build_service()
    _patch_graph(
        monkeypatch,
        service,
        _FakeCompiledGraph([("messages", (reasoning_chunk, {})), _text_event("Trả lời.")]),
        seed_hits=[_hit()],
    )

    text = "".join(service.stream_answer(_request())["answer_stream"])

    assert text == "<think>\nđang suy nghĩ\n</think>\n\nTrả lời."


def test_stream_answer_forwards_tool_status_to_the_callback(monkeypatch: Any) -> None:
    from langchain_core.messages import AIMessage

    update_event = (
        "updates",
        {"agent": {"messages": [AIMessage(content="", tool_calls=[
            {"name": "graph_validate", "args": {"doc_id": "nd15"}, "id": "1"}
        ])]}},
    )
    service = _build_service()
    _patch_graph(
        monkeypatch, service, _FakeCompiledGraph([update_event, _text_event("Trả lời.")]),
        seed_hits=[_hit()],
    )

    statuses: list[str] = []
    result = service.stream_answer(_request(), on_status=statuses.append)
    list(result["answer_stream"])

    assert statuses == ["Đang kiểm tra hiệu lực văn bản..."]
    assert result["retrieval_trace"]["iterations"] == 1


# ----------------------------------------------------------------------
# §4.6 post-hoc safety net
# ----------------------------------------------------------------------


def test_safety_net_warns_when_the_agent_skipped_graph_validate(monkeypatch: Any) -> None:
    service = _build_service(graph_retriever=_FakeGraphRetriever(_graph_context()))
    _patch_graph(
        monkeypatch,
        service,
        _FakeCompiledGraph([_text_event("Trả lời.")]),
        seed_hits=[_hit(effect_status="Hết hiệu lực")],
    )

    result = service.stream_answer(_request())
    text = "".join(result["answer_stream"])

    from agent_service import EXPIRY_WARNING

    assert text.endswith(EXPIRY_WARNING)
    assert result["retrieval_trace"]["graph_validation"] == "post_hoc"
    assert result["retrieval_trace"]["resolutions"][0]["action"] == "expired_warning"


def test_safety_net_suppresses_footer_when_the_answer_already_warns(monkeypatch: Any) -> None:
    service = _build_service(graph_retriever=_FakeGraphRetriever(_graph_context()))
    _patch_graph(
        monkeypatch,
        service,
        _FakeCompiledGraph([_text_event("Văn bản này ⚠️ đã hết hiệu lực.")]),
        seed_hits=[_hit(effect_status="Hết hiệu lực")],
    )

    text = "".join(service.stream_answer(_request())["answer_stream"])

    from agent_service import EXPIRY_WARNING

    # Model already warned inline — no duplicated blanket footer.
    assert EXPIRY_WARNING not in text


def test_safety_net_ignores_an_expired_doc_outside_the_top_three_hits(monkeypatch: Any) -> None:
    service = _build_service(graph_retriever=_FakeGraphRetriever(_graph_context()))
    seed_hits = [
        _hit(doc_id="a", chunk_id="chunk:a:1"),
        _hit(doc_id="b", chunk_id="chunk:b:1"),
        _hit(doc_id="c", chunk_id="chunk:c:1"),
        _hit(doc_id="d", chunk_id="chunk:d:1", effect_status="Hết hiệu lực"),
    ]
    _patch_graph(
        monkeypatch, service, _FakeCompiledGraph([_text_event("Trả lời.")]), seed_hits=seed_hits
    )

    text = "".join(service.stream_answer(_request())["answer_stream"])

    from agent_service import EXPIRY_WARNING

    # The only expired doc is ranked 4th — tangential, so no footer.
    assert EXPIRY_WARNING not in text


def test_safety_net_is_silent_when_every_document_is_in_force(monkeypatch: Any) -> None:
    service = _build_service(graph_retriever=_FakeGraphRetriever(_graph_context()))
    _patch_graph(
        monkeypatch, service, _FakeCompiledGraph([_text_event("Trả lời.")]), seed_hits=[_hit()]
    )

    text = "".join(service.stream_answer(_request())["answer_stream"])

    assert text == "Trả lời."


def test_safety_net_is_skipped_when_the_agent_called_graph_validate(monkeypatch: Any) -> None:
    service = _build_service(graph_retriever=_FakeGraphRetriever(_graph_context()))

    def _fake_build(request: Any, state: Any) -> Any:
        state.hits.append(_hit(effect_status="Hết hiệu lực"))
        state.graph_validation = "agent_tool"
        return _FakeCompiledGraph([_text_event("Trả lời.")])

    monkeypatch.setattr(service, "_build_graph", _fake_build)

    result = service.stream_answer(_request())
    text = "".join(result["answer_stream"])

    assert text == "Trả lời."
    assert result["retrieval_trace"]["graph_validation"] == "agent_tool"


def test_concurrent_runs_do_not_share_state(monkeypatch: Any) -> None:
    """Pipe is a singleton: two overlapping requests must not mix citations."""
    service = _build_service()

    def _fake_build(request: Any, state: Any) -> Any:
        state.hits.append(_hit(doc_id=request.query, chunk_id=f"chunk:{request.query}"))
        return _FakeCompiledGraph([_text_event("Trả lời.")])

    monkeypatch.setattr(service, "_build_graph", _fake_build)

    first = service.stream_answer(_request("alpha"))
    second = service.stream_answer(_request("beta"))
    list(first["answer_stream"])
    list(second["answer_stream"])

    assert [cite["doc_id"] for cite in first["citations"]] == ["alpha"]
    assert [cite["doc_id"] for cite in second["citations"]] == ["beta"]


# ----------------------------------------------------------------------
# <think> block balancing
#
# Qwen3 inlines <think> in content and never sets reasoning_content, so the
# tags stream through us untouched. If a block is left open, Open WebUI folds
# the answer and the citations into the collapsed reasoning bubble.
# ----------------------------------------------------------------------


def _tool_call_event() -> tuple[str, tuple[Any, dict[str, Any]]]:
    from langchain_core.messages import AIMessageChunk

    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": "retrieval_search", "args": '{"query": "x"}', "id": "1", "index": 0}
        ],
    )
    return ("messages", (chunk, {}))


def test_stream_closes_think_block_truncated_by_max_tokens(monkeypatch: Any) -> None:
    """max_tokens can cut generation off mid-reasoning, so </think> never arrives."""
    service = _build_service()
    _patch_graph(
        monkeypatch,
        service,
        _FakeCompiledGraph([_text_event("\n<think>\n"), _text_event("suy luận dở dang")]),
        seed_hits=[_hit()],
    )

    text = "".join(service.stream_answer(_request())["answer_stream"])

    assert text.count("<think>") == text.count("</think>") == 1
    assert text.rstrip().endswith("</think>")


def test_stream_does_not_double_close_a_well_formed_think_block(monkeypatch: Any) -> None:
    service = _build_service()
    _patch_graph(
        monkeypatch,
        service,
        _FakeCompiledGraph(
            [
                # Tags arrive split across chunks, exactly as the endpoint sends them.
                _text_event("\n<think>\nsuy luận\n</"),
                _text_event("think>\n\n"),
                _text_event("Câu trả lời."),
            ]
        ),
        seed_hits=[_hit()],
    )

    text = "".join(service.stream_answer(_request())["answer_stream"])

    assert text.count("</think>") == 1
    assert text.endswith("Câu trả lời.")


def test_stream_closes_think_block_left_open_by_a_tool_call(monkeypatch: Any) -> None:
    """A turn ending in a tool call stops before </think>; the next turn reopens one."""
    service = _build_service()
    _patch_graph(
        monkeypatch,
        service,
        _FakeCompiledGraph(
            [
                _text_event("\n<think>\ncần tra cứu"),
                _tool_call_event(),
                _text_event("\n<think>\nđã có kết quả\n</think>\n\n"),
                _text_event("Câu trả lời cuối."),
            ]
        ),
        seed_hits=[_hit()],
    )

    text = "".join(service.stream_answer(_request())["answer_stream"])

    assert text.count("<think>") == text.count("</think>") == 2
    # The answer must sit outside every reasoning block.
    assert text.endswith("Câu trả lời cuối.")
    assert "Câu trả lời cuối." not in text[: text.rfind("</think>")]
