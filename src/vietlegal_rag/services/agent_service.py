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

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately

from agent_tools import (
    AgentRunState,
    make_graph_validate_tool,
    make_retrieval_tool,
    make_web_search_tool,
)
from citation_formatter import shorten_title
from think_tags import CLOSER, has_unclosed_think
from context_assembler import ContextAssembler
from document_resolver import DocumentResolver
from lightrag_service import LightRAGService
from retrieval_modes import RetrievalRequest

logger = logging.getLogger("vietlegal_rag.services.agent_service")

_AGENT_SYSTEM_PROMPT_TEMPLATE = """Bạn là trợ lý pháp lý Việt Nam. Bạn chỉ được trả lời dựa trên kết quả trả về từ các công cụ, tuyệt đối không bịa căn cứ pháp lý và không trả lời từ trí nhớ sẵn có.

QUY TRÌNH BẮT BUỘC:
1. Luôn gọi `retrieval_search` trước tiên để tìm văn bản pháp luật liên quan. Hãy viết lại câu hỏi của người dùng thành truy vấn giàu từ khoá pháp lý.
2. Với MỌI văn bản bạn định trích dẫn, bắt buộc gọi `graph_validate` với `doc_id` của văn bản đó (lấy từ kết quả `retrieval_search`, không dùng tiêu đề) trước khi trích dẫn.
3. Nếu `effect_verdict` là `expired` hoặc `superseded`, bạn PHẢI cảnh báo rõ ràng cho người dùng, đồng thời dựa câu trả lời trên văn bản mới hơn (gọi thêm `retrieval_search` để lấy nội dung văn bản thay thế nếu cần) và nêu rõ điểm đã thay đổi.
{web_step}
GIỚI HẠN: tối đa {max_iterations} lượt gọi công cụ, và bạn PHẢI để dành lượt cuối cho câu trả lời. Đừng gọi lại một công cụ với tham số đã dùng. Khi đã đủ căn cứ, hãy trả lời NGAY thay vì gọi thêm công cụ. Nếu các công cụ không trả về thông tin hữu ích, hãy nói rõ rằng bạn không tìm được đủ căn cứ pháp lý thay vì suy đoán.

Câu trả lời cuối cùng phải bằng tiếng Việt, ngắn gọn, nêu rõ căn cứ và cảnh báo hiệu lực nếu có."""

_WEB_STEP = """4. Gọi `web_find_source_link` một lần cho mỗi văn bản được trích dẫn để lấy đường dẫn nguồn chính thống. Nếu công cụ trả về `[]`, hãy trích dẫn không kèm đường dẫn — tuyệt đối không tự bịa URL.
"""


def _system_prompt(web_search_enabled: bool, max_iterations: int) -> str:
    """Build the prompt for the tools actually registered this run.

    The web step is omitted when web search is disabled: NoopWebSearch can only ever
    return [], so mandating a call per cited document spends the iteration budget on
    guaranteed-empty results and the model runs out of turns before it answers.
    """
    return _AGENT_SYSTEM_PROMPT_TEMPLATE.format(
        web_step=_WEB_STEP if web_search_enabled else "",
        max_iterations=max_iterations,
    )

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

# count_tokens_approximately defaults to 4 chars/token, which is an English ratio.
# Vietnamese legal text measures ~2.1 (tiktoken counts 980 tokens where the default
# estimates 514), and an underestimate here spends budget we do not have — the whole
# point is to stay under a hard provider limit, so estimate against Vietnamese.
_CHARS_PER_TOKEN = 2.0

# Floor for the prompt budget: below this the newest tool result cannot survive and
# the agent is useless anyway. Misconfiguration surfaces as a provider error rather
# than as silently blanked context.
_MIN_PROMPT_TOKENS = 512

# Every token count here is an estimate, and the provider's is authoritative: budget
# to exactly the limit and a small underestimate is still a rejected request. Give
# the estimate room to be wrong.
_SAFETY_MARGIN_TOKENS = 400

# Prompt ceiling for the forced final answer. The model's chain of thought scales
# with how much clutter it is handed: on a 45-token prompt it concludes in ~1400
# tokens, but given a full run's worth of tool results it reasons past max_tokens
# and returns nothing at all. The final turn needs the best few results, not all of
# them, so it is trimmed hard and spends what is left on the answer.
_FORCED_ANSWER_PROMPT_TOKENS = 1500

# Sent on the forced turn. Without it the model reasons about the tool call it would
# like to make next, finds no tools bound, and stops mid-thought — terminating the
# run but answering nothing. It has to be told the tools are gone for good.
_FORCE_ANSWER_DIRECTIVE = (
    "DỪNG gọi công cụ — không còn công cụ nào khả dụng và bạn sẽ không được gọi thêm. "
    "Dựa HOÀN TOÀN vào các kết quả đã có ở trên, hãy viết NGAY câu trả lời cuối cùng "
    "bằng tiếng Việt cho câu hỏi của người dùng: nêu mức phạt/quy định cùng căn cứ "
    "(tên văn bản, điều khoản) và cảnh báo hiệu lực nếu có. Nếu căn cứ chưa đầy đủ, "
    "hãy nói rõ phần nào còn thiếu thay vì suy đoán."
)

# Stands in for an older tool result dropped from the prompt. Elided results stay
# in AgentRunState, so citations still resolve from hits the LLM can no longer see.
# It must not invite a retry: an earlier version suggested calling the tool again,
# and the model obliged, re-fetched a result that was elided again, and looped until
# the recursion limit. Tell it to move on instead.
_ELIDED_TOOL_CONTENT = (
    '{"note": "Kết quả này đã được lược bỏ để tiết kiệm ngữ cảnh. '
    'ĐỪNG gọi lại công cụ cho nội dung này — hãy dùng các kết quả còn lại '
    'và trả lời ngay."}'
)


# Marks a tool result cut mid-JSON so the model treats it as incomplete rather than
# as the full result set.
_TRUNCATION_SUFFIX = (
    ' ... [KẾT QUẢ BỊ CẮT BỚT do giới hạn ngữ cảnh. Hãy dùng phần đã có để trả lời.]'
)


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


def _close_dangling_think(thinking: dict[str, Any]) -> Generator[str, None, None]:
    """Close a ``<think>`` block the model left open, if there is one.

    Covers both shapes: a block we opened around ``reasoning_content``, and one
    the model inlined in its content stream but never closed. Left open, Open
    WebUI folds the answer and the citations into the reasoning bubble.
    """
    if thinking["open"]:
        thinking["open"] = False
        thinking["content"] = ""
        yield CLOSER
        return
    if has_unclosed_think(thinking["content"]):
        thinking["content"] = ""
        yield CLOSER


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
        max_request_tokens: int = 8000,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.graph_retriever = graph_retriever
        self.document_resolver = document_resolver
        self.web_search = web_search
        self.llm = llm
        self.fallback_service = fallback_service
        self.max_iterations = max_iterations
        self.max_request_tokens = max_request_tokens

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

    def _prompt_budget(
        self, request: RetrievalRequest, tools: list[Any], system_prompt: str
    ) -> int:
        """Tokens left for the prompt once output and fixed overhead are paid for.

        Providers count reserved output against the same limit as the prompt, so a
        4096-token ``max_tokens`` spends half of Groq's 8000 before a single word of
        context is sent. The system prompt and tool schemas ride along with every
        request but never appear in ``state["messages"]``, so they are measured here
        rather than trimmed later.
        """
        overhead = count_tokens_approximately(
            [SystemMessage(content=system_prompt)],
            tools=tools,
            chars_per_token=_CHARS_PER_TOKEN,
        )
        budget = (
            self.max_request_tokens
            - request.llm.max_tokens
            - overhead
            - _SAFETY_MARGIN_TOKENS
        )
        return max(budget, _MIN_PROMPT_TOKENS)

    def _trim_for_model(self, messages: list[Any], budget: int) -> list[Any]:
        """Cap the prompt at ``budget`` by eliding the oldest tool results.

        Tool results accumulate every iteration, so an 8-step run can outgrow the
        provider's request limit (HTTP 413). Only ToolMessage content is shrunk,
        never dropped: removing a ToolMessage would orphan the tool_calls on the
        AIMessage before it and the provider rejects that outright. Newest results
        are kept because those are what the model is currently reasoning about —
        older ones are elided wholesale, and the newest is truncated only if it
        blows the budget on its own (the model may ask for a large top_k).
        """
        def cost(message: Any) -> int:
            return count_tokens_approximately(
                [message], chars_per_token=_CHARS_PER_TOKEN
            )

        # Start from the cheapest legal prompt — every tool result elided — then buy
        # back the newest results while the budget allows. Sizing each message as we
        # walk instead would let the newest result claim the whole budget and push
        # the total over it, since the messages around it still have to be sent.
        result = [
            message.model_copy(update={"content": _ELIDED_TOOL_CONTENT})
            if isinstance(message, ToolMessage)
            else message
            for message in messages
        ]
        used = sum(cost(message) for message in result)

        for index in range(len(messages) - 1, -1, -1):
            original = messages[index]
            if not isinstance(original, ToolMessage):
                continue
            elided_cost = cost(result[index])
            if used - elided_cost + cost(original) <= budget:
                used += cost(original) - elided_cost
                result[index] = original
                continue
            # Does not fit whole: give the newest result whatever is left rather than
            # nothing, and leave everything older elided.
            truncated = self._truncate_tool_message(original, budget - used + elided_cost)
            if truncated is not None and used - elided_cost + cost(truncated) <= budget:
                used += cost(truncated) - elided_cost
                result[index] = truncated
            break

        return result

    @staticmethod
    def _truncate_tool_message(message: ToolMessage, allowance: int) -> ToolMessage | None:
        """Cut a tool result down to ``allowance`` tokens, or None if it cannot fit.

        The result is measured rather than derived from the character count: a
        message also pays for its name and envelope, so chars/_CHARS_PER_TOKEN alone
        overshoots the allowance and the caller then rejects the message outright,
        eliding a result that could have partly fit.
        """
        if allowance <= 0:
            return None
        content = str(message.content or "")
        keep_chars = int(allowance * _CHARS_PER_TOKEN) - len(_TRUNCATION_SUFFIX)
        while keep_chars > 0:
            if len(content) <= keep_chars:
                return message
            candidate = message.model_copy(
                update={"content": content[:keep_chars] + _TRUNCATION_SUFFIX}
            )
            if (
                count_tokens_approximately([candidate], chars_per_token=_CHARS_PER_TOKEN)
                <= allowance
            ):
                return candidate
            keep_chars -= 64
        return None

    def _pre_model_hook(self, state: dict[str, Any], budget: int) -> dict[str, Any]:
        messages = state["messages"]
        forcing = self._iterations_used(messages) >= self.max_iterations
        if forcing:
            budget = min(budget, _FORCED_ANSWER_PROMPT_TOKENS)
        try:
            trimmed = self._trim_for_model(list(messages), budget)
        except Exception:
            # Never fail the run over trimming; an oversized prompt still has the
            # fallback path behind it, a raised hook has nothing.
            logger.warning("Agent prompt trimming failed; sending untrimmed", exc_info=True)
            trimmed = list(messages)
        if forcing:
            trimmed.append(HumanMessage(content=_FORCE_ANSWER_DIRECTIVE))
        return {"llm_input_messages": trimmed}

    def _web_search_enabled(self) -> bool:
        from web_search_service import NoopWebSearch

        return self.web_search is not None and not isinstance(self.web_search, NoopWebSearch)

    @staticmethod
    def _iterations_used(messages: Any) -> int:
        """Tool-calling turns taken so far."""
        return sum(
            1
            for message in messages
            if isinstance(message, AIMessage) and message.tool_calls
        )

    def _model_for_state(
        self, state: Any, request: RetrievalRequest, tools: list[Any]
    ) -> Any:
        """Bind tools only while the iteration budget lasts, then force an answer.

        The 27B model does not stop on instruction: told the budget was spent, or
        handed a "you already searched this" note, it re-issues the same call until
        the graph dies at the recursion limit and the whole run is thrown away.
        Unbinding the tools removes the option — with nothing to call, the only move
        left is the final answer, and the run always terminates.
        """
        llm = self._request_llm(request)
        messages = state["messages"] if isinstance(state, dict) else state.messages
        if self._iterations_used(messages) >= self.max_iterations:
            logger.info(
                "Agent hit its %d-iteration budget; forcing a final answer",
                self.max_iterations,
            )
            return llm
        return llm.bind_tools(tools)

    def _build_graph(self, request: RetrievalRequest, state: AgentRunState) -> Any:
        from langgraph.prebuilt import create_react_agent

        web_enabled = self._web_search_enabled()
        system_prompt = _system_prompt(web_enabled, self.max_iterations)
        tools = [
            make_retrieval_tool(self.retrieval_service, request, state),
            make_graph_validate_tool(self.graph_retriever, self.document_resolver, state),
        ]
        if web_enabled:
            tools.append(make_web_search_tool(self.web_search, state))
        budget = self._prompt_budget(request, tools, system_prompt)
        return create_react_agent(
            lambda s, _runtime: self._model_for_state(s, request, tools),
            tools,
            prompt=system_prompt,
            pre_model_hook=lambda s: self._pre_model_hook(s, budget),
        )

    def _graph_config(self) -> dict[str, Any]:
        # Each tool-calling iteration costs three node executions: the pre_model_hook
        # that trims the prompt, the model, then the tool. Budgeting two per
        # iteration exhausts the recursion limit around iteration 6, before
        # _model_for_state can unbind the tools and force the final answer — the run
        # would die at the limit instead of answering. The +4 covers the forced
        # answer turn (hook + model) plus headroom.
        return {"recursion_limit": 3 * self.max_iterations + 4}

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

            thinking: dict[str, Any] = {"open": False, "content": ""}
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

            # Runs before the safety-net warning and before pipe.py appends the
            # citations block, so neither ends up inside the reasoning bubble.
            yield from _close_dangling_think(thinking)
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
            # A turn that ends in a tool call stops before emitting </think>, and
            # the next turn opens a fresh <think>. Close it here so the blocks do
            # not nest across turns and swallow the final answer.
            yield from _close_dangling_think(thinking)
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
            yield CLOSER
            thinking["open"] = False
        thinking["content"] += text
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
