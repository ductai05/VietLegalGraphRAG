"""LangGraph ReAct agent, drop-in compatible with LightRAGService.

``answer`` / ``stream_answer`` return the same dict shape as LightRAGService so
``pipe.py`` routing is a one-line service swap. LightRAGService also doubles as
the fallback whenever the agent fails, times out, or produces no answer.
"""
from __future__ import annotations

import itertools
import logging
import time
from typing import Any, Callable, Generator

from langchain_core.messages import AIMessage, AIMessageChunk

from agent_tools import (
    AgentRunState,
    make_graph_validate_tool,
    make_retrieval_tool,
    make_web_search_tool,
)
from citation_formatter import shorten_title
from context_assembler import ContextAssembler
from document_resolver import DocumentResolver
from lightrag_service import LightRAGService
from retrieval_modes import RetrievalRequest

logger = logging.getLogger("vietlegal_rag.services.agent_service")

AGENT_SYSTEM_PROMPT = """Bạn là trợ lý pháp lý Việt Nam. Bạn chỉ được trả lời dựa trên kết quả trả về từ các công cụ, tuyệt đối không bịa căn cứ pháp lý và không trả lời từ trí nhớ sẵn có.

QUY TRÌNH BẮT BUỘC:
1. Luôn gọi `retrieval_search` trước tiên để tìm văn bản pháp luật liên quan. Hãy viết lại câu hỏi của người dùng thành truy vấn giàu từ khoá pháp lý.
2. Với MỌI văn bản bạn định trích dẫn, bắt buộc gọi `graph_validate` với `doc_id` của văn bản đó (lấy từ kết quả `retrieval_search`, không dùng tiêu đề) trước khi trích dẫn.
3. Nếu `effect_verdict` là `expired` hoặc `superseded`, bạn PHẢI cảnh báo rõ ràng cho người dùng, đồng thời dựa câu trả lời trên văn bản mới hơn (gọi thêm `retrieval_search` để lấy nội dung văn bản thay thế nếu cần) và nêu rõ điểm đã thay đổi.
4. Gọi `web_find_source_link` một lần cho mỗi văn bản được trích dẫn để lấy đường dẫn nguồn chính thống. Nếu công cụ trả về `[]`, hãy trích dẫn không kèm đường dẫn — tuyệt đối không tự bịa URL.

GIỚI HẠN: tối đa 8 lượt gọi công cụ. Nếu các công cụ không trả về thông tin hữu ích, hãy nói rõ rằng bạn không tìm được đủ căn cứ pháp lý thay vì suy đoán.

Câu trả lời cuối cùng phải bằng tiếng Việt, ngắn gọn, nêu rõ căn cứ và cảnh báo hiệu lực nếu có."""

EXPIRY_WARNING = (
    "⚠️ Lưu ý: một số căn cứ được trích dẫn có thể đã hết hiệu lực "
    "hoặc đã có phiên bản mới hơn."
)

AGENT_UNAVAILABLE_MESSAGE = (
    "⚠️ Không thể tạo câu trả lời từ agent và không có luồng dự phòng khả dụng."
)

_TOOL_STATUS = {
    "retrieval_search": "Đang tìm kiếm văn bản pháp luật...",
    "graph_validate": "Đang kiểm tra hiệu lực văn bản...",
    "web_find_source_link": "Đang tìm nguồn trích dẫn chính thống...",
}

_WARNING_ACTIONS = {"replaced", "expired_warning", "superseded"}


def _chunk_text(chunk: Any) -> str:
    """Flatten an AIMessageChunk's content into plain text."""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return "".join(parts)
    return ""


def _final_answer_text(messages: list[Any]) -> str:
    for message in reversed(messages or []):
        if not isinstance(message, AIMessage):
            continue
        if getattr(message, "tool_calls", None):
            continue
        text = _chunk_text(message).strip()
        if text:
            return text
    return ""


def _safe_status(on_status: Callable[[str], None] | None, description: str) -> None:
    if on_status is None:
        return
    try:
        on_status(description)
    except Exception:
        logger.warning("Agent status callback failed", exc_info=True)


class AgentService:
    def __init__(
        self,
        retrieval_service: Any,
        graph_retriever: Any,
        document_resolver: DocumentResolver,
        web_search: Any,
        llm: Any,
        fallback_service: LightRAGService | None = None,
        max_iterations: int = 8,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.graph_retriever = graph_retriever
        self.document_resolver = document_resolver
        self.web_search = web_search
        self.llm = llm
        self.fallback_service = fallback_service
        self.max_iterations = max_iterations

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _request_llm(self, request: RetrievalRequest) -> Any:
        """Rebind the injected chat model to this request's LLM settings."""
        try:
            return self.llm.model_copy(
                update={
                    "temperature": request.llm.temperature,
                    "max_tokens": request.llm.max_tokens,
                }
            )
        except Exception:
            logger.warning("Could not rebind LLM per request; using defaults", exc_info=True)
            return self.llm

    def _build_graph(self, request: RetrievalRequest, state: AgentRunState) -> Any:
        from langgraph.prebuilt import create_react_agent

        tools = [
            make_retrieval_tool(self.retrieval_service, request, state),
            make_graph_validate_tool(self.graph_retriever, self.document_resolver, state),
            make_web_search_tool(self.web_search, state),
        ]
        return create_react_agent(
            self._request_llm(request), tools, prompt=AGENT_SYSTEM_PROMPT
        )

    def _graph_config(self) -> dict[str, Any]:
        # Each tool-calling iteration costs a model step plus a tool step.
        return {"recursion_limit": 2 * self.max_iterations + 3}

    @staticmethod
    def _graph_input(request: RetrievalRequest) -> dict[str, Any]:
        return {"messages": [{"role": "user", "content": request.query}]}

    # ------------------------------------------------------------------
    # Result assembly
    # ------------------------------------------------------------------

    def _citations(self, state: AgentRunState) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for hit in state.hits:
            dedup_key = (hit.title, hit.citation)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            cite: dict[str, Any] = {
                "chunk_id": hit.chunk_id,
                "doc_id": hit.doc_id,
                "title": hit.title,
                "citation": hit.citation,
            }
            url = state.links.get(shorten_title(hit.title or ""))
            if url:
                cite["url"] = url
            verdict = state.verdicts.get(DocumentResolver._clean_id(hit.doc_id))
            if verdict:
                cite["effect_verdict"] = verdict
            if hit.effect_status:
                cite["effect_status"] = hit.effect_status
            citations.append(cite)
        return citations

    def _trace(self, state: AgentRunState, started: float) -> dict[str, Any]:
        trace: dict[str, Any] = {
            "mode": "agent",
            "tool_calls": state.tool_calls,
            "tools_used": list(state.tools_used),
            "iterations": state.iterations,
            "graph_validation": state.graph_validation,
            "latency_ms": {"total": round((time.perf_counter() - started) * 1000, 3)},
        }
        if state.resolutions:
            trace["resolutions"] = list(state.resolutions)
        return trace

    def _run_safety_net(self, request: RetrievalRequest, state: AgentRunState) -> str:
        """§4.6: the ReAct agent may skip graph_validate — resolve deterministically.

        Returns the warning line to append to the answer, or "".
        """
        if state.graph_validation != "none" or not state.hits:
            return ""
        try:
            graph_context = self.graph_retriever.retrieve(
                request.query,
                [hit.to_dict() for hit in state.hits],
                request.graph.max_hops,
                auto_depth=request.graph.auto_depth,
            )
            # ContextAssembler is stateful and dependencies.py builds exactly one,
            # so use a per-request instance over the shared, stateless resolver.
            assembler = ContextAssembler(document_resolver=self.document_resolver)
            assembler.merge(list(state.hits), graph_context)
            resolved = assembler.last_resolved
        except Exception:
            logger.exception("Post-hoc graph validation failed")
            return ""

        state.graph_payload = graph_context.to_dict()
        state.graph_validation = "post_hoc"
        if resolved is None:
            return ""
        state.resolutions.extend(item.to_dict() for item in resolved.resolutions)
        if any(item.action in _WARNING_ACTIONS for item in resolved.resolutions):
            return "\n\n" + EXPIRY_WARNING
        return ""

    # ------------------------------------------------------------------
    # Non-streaming entrypoint
    # ------------------------------------------------------------------

    def answer(self, request: RetrievalRequest) -> dict[str, Any]:
        started = time.perf_counter()
        state = AgentRunState()
        try:
            graph = self._build_graph(request, state)
            result = graph.invoke(self._graph_input(request), config=self._graph_config())
            messages = result.get("messages") or []
            answer_text = _final_answer_text(messages)
            if not answer_text:
                raise RuntimeError("agent produced no answer text")
            state.iterations = sum(
                1
                for message in messages
                if isinstance(message, AIMessage) and message.tool_calls
            )
        except Exception:
            logger.exception("Agent run failed; falling back to the static flow")
            return self._fallback_answer(request, "agent.invoke_failed")

        answer_text += self._run_safety_net(request, state)
        return {
            "answer": answer_text,
            "citations": self._citations(state),
            "retrieval_context": [hit.to_dict() for hit in state.hits],
            "graph_context": state.graph_payload,
            "retrieval_trace": self._trace(state, started),
        }

    def _fallback_answer(self, request: RetrievalRequest, error_code: str) -> dict[str, Any]:
        if self.fallback_service is None:
            return {
                "answer": AGENT_UNAVAILABLE_MESSAGE,
                "citations": [],
                "retrieval_context": [],
                "graph_context": {},
                "retrieval_trace": {"mode": "agent", "agent_error": error_code},
            }
        result = self.fallback_service.answer(request)
        trace = dict(result.get("retrieval_trace") or {})
        trace["mode"] = "agent_fallback"
        trace["agent_error"] = error_code
        result["retrieval_trace"] = trace
        return result

    # ------------------------------------------------------------------
    # Streaming entrypoint
    # ------------------------------------------------------------------

    def stream_answer(
        self,
        request: RetrievalRequest,
        on_status: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        state = AgentRunState()

        # pipe.py reads these off the returned dict *before* draining
        # answer_stream and renders them *after*, so the generator populates
        # these exact objects in place rather than rebinding them.
        citations: list[dict[str, Any]] = []
        retrieval_context: list[dict[str, Any]] = []
        graph_payload: dict[str, Any] = {}
        trace: dict[str, Any] = {"mode": "agent"}

        def _finalize() -> None:
            citations[:] = self._citations(state)
            retrieval_context[:] = [hit.to_dict() for hit in state.hits]
            graph_payload.clear()
            graph_payload.update(state.graph_payload)
            trace.clear()
            trace.update(self._trace(state, started))

        def _fallback(error_code: str) -> Generator[str, None, None]:
            if self.fallback_service is None:
                trace["agent_error"] = error_code
                yield AGENT_UNAVAILABLE_MESSAGE
                return
            try:
                result = self.fallback_service.stream_answer(request)
            except Exception:
                logger.exception("Static fallback failed to start")
                trace["agent_error"] = error_code
                yield AGENT_UNAVAILABLE_MESSAGE
                return
            citations[:] = result.get("citations") or []
            retrieval_context[:] = result.get("retrieval_context") or []
            graph_payload.clear()
            graph_payload.update(result.get("graph_context") or {})
            trace.clear()
            trace.update(result.get("retrieval_trace") or {})
            trace["mode"] = "agent_fallback"
            trace["agent_error"] = error_code
            yield from result["answer_stream"]

        def _generate() -> Generator[str, None, None]:
            try:
                graph = self._build_graph(request, state)
                events = graph.stream(
                    self._graph_input(request),
                    config=self._graph_config(),
                    stream_mode=["updates", "messages"],
                )
                iterator = iter(events)
                # Pull the first event inside the try so a dead LLM falls back
                # instead of surfacing mid-answer.
                first_event = next(iterator)
            except StopIteration:
                yield from _fallback("agent.empty_stream")
                return
            except Exception:
                logger.exception("Agent stream failed to start; falling back")
                yield from _fallback("agent.stream_failed")
                return

            thinking = {"open": False}
            produced_answer = False
            try:
                for event in itertools.chain([first_event], iterator):
                    for token in self._event_tokens(event, state, on_status, thinking):
                        produced_answer = True
                        yield token
            except Exception:
                logger.exception("Agent stream iteration failed")
                if not produced_answer:
                    yield from _fallback("agent.stream_failed")
                    return
                yield "\n⚠️ Đã xảy ra lỗi khi tạo câu trả lời từ mô hình ngôn ngữ."
                _finalize()
                return

            if thinking["open"]:
                yield "\n</think>\n\n"
            if not produced_answer:
                yield from _fallback("agent.no_answer")
                return

            warning = self._run_safety_net(request, state)
            if warning:
                yield warning
            _finalize()

        return {
            "answer_stream": _generate(),
            "citations": citations,
            "retrieval_context": retrieval_context,
            "graph_context": graph_payload,
            "retrieval_trace": trace,
        }

    def _event_tokens(
        self,
        event: Any,
        state: AgentRunState,
        on_status: Callable[[str], None] | None,
        thinking: dict[str, bool],
    ) -> Generator[str, None, None]:
        if not isinstance(event, tuple) or len(event) != 2:
            return
        mode, payload = event

        if mode == "updates":
            self._handle_updates(payload, state, on_status)
            return
        if mode != "messages":
            return

        chunk = payload[0] if isinstance(payload, tuple) and payload else None
        if not isinstance(chunk, AIMessageChunk):
            return
        # Tool-call arguments are not answer text.
        if getattr(chunk, "tool_call_chunks", None):
            return

        reasoning = (getattr(chunk, "additional_kwargs", None) or {}).get(
            "reasoning_content"
        )
        if reasoning:
            if not thinking["open"]:
                yield "<think>\n"
                thinking["open"] = True
            yield reasoning
            return

        text = _chunk_text(chunk)
        if not text:
            return
        if thinking["open"]:
            yield "\n</think>\n\n"
            thinking["open"] = False
        yield text

    @staticmethod
    def _handle_updates(
        payload: Any,
        state: AgentRunState,
        on_status: Callable[[str], None] | None,
    ) -> None:
        if not isinstance(payload, dict):
            return
        for update in payload.values():
            if not isinstance(update, dict):
                continue
            for message in update.get("messages") or []:
                tool_calls = getattr(message, "tool_calls", None) or []
                if not tool_calls:
                    continue
                state.iterations += 1
                for call in tool_calls:
                    status = _TOOL_STATUS.get(call.get("name") or "")
                    if status:
                        _safe_status(on_status, status)
