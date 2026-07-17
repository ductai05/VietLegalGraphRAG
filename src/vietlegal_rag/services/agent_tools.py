"""LangChain tool definitions for the ReAct agent.

Every tool is produced by a factory that closes over services already built by
``dependencies.py`` — tools never construct their own clients. Every tool
returns a JSON string and never raises: the LLM must always get a readable
result, including on failure.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from citation_formatter import shorten_title
from contracts import RetrievalHit
from document_resolver import DocumentResolver
from retrieval_modes import RetrievalRequest

logger = logging.getLogger("vietlegal_rag.services.agent_tools")

# Per-chunk excerpt cap. Sized so a 5-hit result (~3500 chars, ~1750 Vietnamese
# tokens) leaves room for a second search plus the answer inside the agent's prompt
# budget; at 1500 a single result filled the budget on its own and every follow-up
# search forced the previous one to be elided.
MAX_TOOL_TEXT_CHARS = 700

# DocumentResolver.ResolutionInfo.action -> effect_verdict (§4.3).
_ACTION_TO_VERDICT = {
    "kept": "in_force",
    "replaced": "expired",
    "expired_warning": "expired",
    "superseded": "superseded",
}

# When several contexts for one doc_id disagree, the most severe verdict wins.
_VERDICT_SEVERITY = {"unknown": 0, "in_force": 1, "superseded": 2, "expired": 3}


@dataclass
class AgentRunState:
    """Per-request collector. One instance per ``answer`` / ``stream_answer``
    call — never shared, because ``Pipe`` is a singleton serving concurrent
    requests."""

    hits: list[RetrievalHit] = field(default_factory=list)
    graph_payload: dict[str, Any] = field(default_factory=dict)
    resolutions: list[dict[str, Any]] = field(default_factory=list)
    # Keyed by shortened title: the web tool only ever sees a title, never a doc_id.
    links: dict[str, str] = field(default_factory=dict)
    verdicts: dict[str, str] = field(default_factory=dict)
    tool_calls: int = 0
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    # "none" | "agent_tool" | "post_hoc" — see the §4.6 safety net.
    graph_validation: str = "none"
    # Tool calls already served this run, keyed by (tool_name, normalised args).
    seen_calls: set[tuple[str, str]] = field(default_factory=set)

    def record(self, tool_name: str) -> None:
        self.tool_calls += 1
        if tool_name not in self.tools_used:
            self.tools_used.append(tool_name)

    def is_repeat(self, tool_name: str, key: str) -> bool:
        """True when this exact call was already served.

        The 27B model re-issues an identical search instead of moving on, burning
        the iteration budget on a result it already has until the run dies at the
        recursion limit. Re-running the query cannot produce new information, so
        the caller answers from cache and tells the model to stop.
        """
        dedup_key = (tool_name, key.strip().lower())
        if dedup_key in self.seen_calls:
            return True
        self.seen_calls.add(dedup_key)
        return False

    def add_hits(self, hits: list[RetrievalHit]) -> None:
        known = {hit.chunk_id for hit in self.hits if hit.chunk_id}
        for hit in hits:
            if hit.chunk_id and hit.chunk_id in known:
                continue
            self.hits.append(hit)
            if hit.chunk_id:
                known.add(hit.chunk_id)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


class RetrievalSearchInput(BaseModel):
    query: str = Field(
        description=(
            "Vietnamese legal search query. Rewrite the user's question into a "
            "keyword-rich query."
        )
    )
    # Capped at 8, not 20: every hit is spent from the agent's prompt budget, and a
    # single 20-hit result would exceed it on its own and starve the answer.
    top_k: int = Field(default=3, ge=1, le=8, description="Number of chunks to return.")


def make_retrieval_tool(
    retrieval_service: Any,
    base_request: RetrievalRequest,
    state: AgentRunState,
) -> StructuredTool:
    """Tool 1: retrieval_search — hybrid ES search over legal chunks."""

    def _run(query: str, top_k: int = 3) -> str:
        state.record("retrieval_search")
        if state.is_repeat("retrieval_search", query):
            return _dumps(
                {
                    "note": (
                        "Bạn đã tìm với truy vấn này rồi và kết quả nằm ở trên. "
                        "ĐỪNG tìm lại. Hãy dùng kết quả đã có để trả lời NGAY, "
                        "hoặc gọi `graph_validate` nếu cần kiểm tra hiệu lực."
                    )
                }
            )
        try:
            # dataclasses.replace re-runs __post_init__, which rejects
            # top_k > candidate_k while reranking.
            effective_top_k = top_k
            if base_request.rerank.enabled:
                effective_top_k = min(top_k, base_request.rerank.candidate_k)
            request = dataclasses.replace(
                base_request, query=query, top_k=effective_top_k
            )
            hits = retrieval_service.search(request)
        except Exception:
            logger.exception("retrieval_search tool failed")
            return _dumps({"error": "retrieval_failed"})

        state.add_hits(list(hits))
        return _dumps(
            [
                {
                    "chunk_id": hit.chunk_id,
                    "doc_id": hit.doc_id,
                    "title": hit.title,
                    "document_number": hit.document_number,
                    "legal_type": hit.legal_type,
                    "effect_status": hit.effect_status,
                    "section_path": hit.section_path,
                    "citation": hit.citation,
                    "text": (hit.text or "")[:MAX_TOOL_TEXT_CHARS],
                }
                for hit in hits
            ]
        )

    return StructuredTool.from_function(
        func=_run,
        name="retrieval_search",
        description=(
            "Tìm kiếm các đoạn văn bản pháp luật Việt Nam theo từ khoá và ngữ nghĩa. "
            "Luôn gọi công cụ này trước tiên. Trả về danh sách JSON gồm doc_id, "
            "citation và nội dung trích dẫn."
        ),
        args_schema=RetrievalSearchInput,
    )


class GraphValidateInput(BaseModel):
    # str | int, not str: a doc_id like "477975" is emitted as a bare number by the
    # model, and providers validate tool args against this schema before the call
    # ever reaches us — a string-only schema gets the call rejected outright.
    # _run normalises back to str.
    doc_id: str | int = Field(
        description=(
            "A doc_id returned by retrieval_search — not a free-text document title."
        )
    )
    depth: int = Field(default=1, ge=1, le=2, description="Graph traversal depth.")


def make_graph_validate_tool(
    graph_retriever: Any,
    document_resolver: DocumentResolver,
    state: AgentRunState,
) -> StructuredTool:
    """Tool 2: graph_validate — neighbours + legal-effect verdict for one document."""

    def _run(doc_id: str | int, depth: int = 1) -> str:
        state.record("graph_validate")
        doc_id = str(doc_id)
        if state.is_repeat("graph_validate", doc_id):
            return _dumps(
                {
                    "note": (
                        "Bạn đã kiểm tra hiệu lực của văn bản này rồi và kết quả nằm ở trên. "
                        "ĐỪNG kiểm tra lại. Hãy trả lời NGAY dựa trên các căn cứ đã có."
                    )
                }
            )
        try:
            clamped_depth = max(1, min(int(depth), 2))
            graph_context = graph_retriever.get_document_neighbors(
                doc_id, depth=clamped_depth
            )
            clean_doc_id = DocumentResolver._clean_id(doc_id)
            contexts = [
                hit.to_answer_context()
                for hit in state.hits
                if DocumentResolver._clean_id(hit.doc_id) == clean_doc_id
            ]
            resolved = document_resolver.resolve(contexts, graph_context)
        except Exception:
            logger.exception("graph_validate tool failed for doc_id=%s", doc_id)
            return _dumps(
                {
                    "doc_id": doc_id,
                    "effect_verdict": "unknown",
                    "available": False,
                    "error": "graph_validate_failed",
                }
            )

        verdict = "unknown"
        replacement_doc_id: str | None = None
        reason = ""
        for context in resolved.contexts:
            if DocumentResolver._clean_id(context.doc_id) != clean_doc_id:
                continue
            resolution = context.resolution or {}
            mapped = _ACTION_TO_VERDICT.get(resolution.get("action") or "")
            if mapped is None:
                continue
            if _VERDICT_SEVERITY[mapped] > _VERDICT_SEVERITY[verdict]:
                verdict = mapped
                replacement_doc_id = resolution.get("replacement_doc_id")
                reason = resolution.get("reason") or ""

        available = graph_context.center is not None
        if not available and verdict == "in_force":
            # Without a graph, "no replacing edge" is not evidence of being in force.
            verdict = "unknown"
            reason = ""

        state.graph_payload = graph_context.to_dict()
        state.resolutions.extend(item.to_dict() for item in resolved.resolutions)
        state.verdicts[clean_doc_id] = verdict
        state.graph_validation = "agent_tool"

        return _dumps(
            {
                "doc_id": doc_id,
                "center": graph_context.center.to_dict() if available else None,
                "relations": [
                    {
                        "source": edge.source,
                        "target": edge.target,
                        "type": edge.type,
                        "raw_label": edge.raw_label,
                        "direction": edge.direction,
                    }
                    for edge in graph_context.edges
                ],
                "effect_verdict": verdict,
                "replacement_doc_id": replacement_doc_id,
                "reason": reason,
                "available": available,
            }
        )

    return StructuredTool.from_function(
        func=_run,
        name="graph_validate",
        description=(
            "Kiểm tra hiệu lực pháp lý và các quan hệ của một văn bản trong đồ thị tri "
            "thức. Bắt buộc gọi cho mọi doc_id trước khi trích dẫn. Trả về "
            "effect_verdict ∈ {in_force, superseded, expired, unknown} và văn bản thay thế nếu có."
        ),
        args_schema=GraphValidateInput,
    )


class WebFindSourceLinkInput(BaseModel):
    document_title: str = Field(
        description='Document title, e.g. "Nghị định 15/2020/NĐ-CP".'
    )
    max_results: int = Field(default=3, ge=1, le=5, description="Number of links.")


def make_web_search_tool(web_search: Any, state: AgentRunState) -> StructuredTool:
    """Tool 3: web_find_source_link — authoritative URL for a cited document."""

    def _run(document_title: str, max_results: int = 3) -> str:
        state.record("web_find_source_link")
        short_title = shorten_title(document_title or "")
        if not short_title.strip():
            return _dumps([])
        try:
            results = web_search.search(f"{short_title} toàn văn", max_results=max_results)
        except Exception:
            logger.exception("web_find_source_link tool failed for %s", short_title)
            return _dumps([])

        results = list(results or [])
        if results:
            state.links.setdefault(short_title, results[0].get("url", ""))
        return _dumps(results)

    return StructuredTool.from_function(
        func=_run,
        name="web_find_source_link",
        description=(
            "Tìm đường dẫn nguồn chính thống (thuvienphapluat.vn, vanban.chinhphu.vn, ...) "
            "cho một văn bản pháp luật. Trả về danh sách JSON, hoặc [] nếu không tìm thấy. "
            "Không bao giờ tự bịa URL."
        ),
        args_schema=WebFindSourceLinkInput,
    )
