# ruff: noqa: E402
import os
import sys
import logging
import asyncio
import queue
import threading
import base64
from typing import Callable, Awaitable, AsyncGenerator, Any
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vietlegal_rag.pipe")
_STREAM_DONE = object()
DEFAULT_LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "16384"))

_OCR_MERGE_PREFIX = "[Nội dung trích từ tài liệu người dùng gửi]:"


def _decode_data_url(url: str) -> tuple[bytes, str] | None:
    # data:<mime>;base64,<payload>
    if not url.startswith("data:") or ";base64," not in url:
        return None
    header, b64 = url.split(";base64,", 1)
    mime = header[len("data:"):].strip()
    try:
        return base64.b64decode(b64), mime
    except Exception:
        return None


def _inline_image_sources(body: dict) -> list[tuple[bytes, str]]:
    messages = body.get("messages") or []
    if not messages:
        return []
    content = messages[-1].get("content")
    if not isinstance(content, list):
        return []
    out: list[tuple[bytes, str]] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "image_url":
            continue
        url = (item.get("image_url") or {}).get("url") or ""
        decoded = _decode_data_url(url)
        if decoded:
            out.append(decoded)
    return out


async def _ocr_one(
    ocr_service: Any,
    content: bytes,
    mime: str,
    *,
    allowed_mimes: frozenset[str],
    max_file_bytes: int,
) -> str:
    if mime not in allowed_mimes:
        logger.info("OCR skip: mime %r not allowed", mime)
        return ""
    if len(content) > max_file_bytes:
        logger.info("OCR skip: %d bytes over cap %d", len(content), max_file_bytes)
        return ""
    try:
        result = await asyncio.to_thread(ocr_service.process, content, mime)
    except Exception:
        logger.warning("OCR provider failed for mime %s", mime, exc_info=True)
        return ""
    if not result or not result.get("success"):
        return ""
    return (result.get("text") or "").strip()


async def _extract_ocr_text(
    body: dict,
    ocr_service: Any,
    file_loader: "Callable[[str], Awaitable[tuple[bytes, str, str] | None]] | None" = None,
    *,
    allowed_mimes: frozenset[str],
    max_file_bytes: int,
) -> str:
    parts: list[str] = []
    for content, mime in _inline_image_sources(body):
        text = await _ocr_one(
            ocr_service, content, mime, allowed_mimes=allowed_mimes, max_file_bytes=max_file_bytes
        )
        if text:
            parts.append(text)
    # Attached files handled in Task 2.
    return "\n\n".join(parts)

# Ensure legacy imports work by adding package directories if not present
from pathlib import Path
_PACKAGE_ROOT = Path(__file__).resolve().parent
_SERVICES_DIR = _PACKAGE_ROOT / "services"
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

class Pipe:
    class Valves(BaseModel):
        # Elasticsearch Config
        elasticsearch_url: str = Field(
            default=os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200"), 
            description="URL to Elasticsearch instance or cloud endpoint"
        )
        elasticsearch_api_key: str = Field(
            default=os.environ.get("ELASTICSEARCH_API_KEY", ""), 
            description="API Key for Elasticsearch Cloud authentication"
        )
        elasticsearch_index: str = Field(
            default=os.environ.get("ELASTICSEARCH_INDEX", "vietlegal_chunks_hybrid_v1"), 
            description="Active Elasticsearch index name"
        )
        
        # Neo4j Config
        neo4j_uri: str = Field(
            default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"), 
            description="Neo4j connection URI"
        )
        neo4j_user: str = Field(
            default=os.environ.get("NEO4J_USER", "neo4j"), 
            description="Neo4j username"
        )
        neo4j_password: str = Field(
            default=os.environ.get("NEO4J_PASSWORD", ""), 
            description="Neo4j password"
        )
        
        # Reranker Config
        rerank_provider: str = Field(
            default=os.environ.get("RERANK_PROVIDER", "noop"), 
            description="Rerank provider ('voyage', 'jina', or 'noop')"
        )
        rerank_model: str = Field(
            default=os.environ.get("RERANK_MODEL", "rerank-2.5"), 
            description="Model identifier for the reranker"
        )
        
        # Embedding Config
        embedding_provider: str = Field(
            default=os.environ.get("EMBEDDING_PROVIDER", "hf"), 
            description="Embedding provider ('hf' or 'onnx')"
        )
        embedding_model: str = Field(
            default=os.environ.get("EMBEDDING_MODEL", "darklethelong/vnlegal-lal"), 
            description="HuggingFace model repository path"
        )
        embedding_onnx_model_path: str = Field(
            default=os.environ.get("EMBEDDING_ONNX_MODEL_PATH", ""), 
            description="Local file path to model.onnx"
        )
        embedding_onnx_tokenizer_path: str = Field(
            default=os.environ.get("EMBEDDING_ONNX_TOKENIZER_PATH", ""), 
            description="Local file path to tokenizer.json"
        )
        
        # LLM Config
        llm_provider: str = Field(
            default=os.environ.get("LLM_PROVIDER", "extractive"), 
            description="LLM provider ('openai-compatible' or 'extractive')"
        )
        llm_base_url: str = Field(
            default=os.environ.get("LLM_BASE_URL", ""), 
            description="Base URL for OpenAI-compatible endpoint"
        )
        llm_api_key: str = Field(
            default=os.environ.get("LLM_API_KEY", ""), 
            description="API Key for OpenAI-compatible model"
        )
        llm_model: str = Field(
            default=os.environ.get("LLM_MODEL", "gpt-4o-mini"), 
            description="LLM model identifier"
        )

        
        # Runtime retrieval settings
        retrieval_mode: str = Field(
            default="hybrid", 
            description="Retrieval mode ('dense', 'sparse', or 'hybrid')"
        )
        top_k: int = Field(
            default=5, 
            description="Number of corpus chunks to retrieve"
        )
        rerank_enabled: bool = Field(
            default=True, 
            description="Whether to rerank initial retrieval hits"
        )
        graph_enabled: bool = Field(
            default=True, 
            description="Whether to perform Neo4j knowledge graph traversal"
        )
        max_hops: int = Field(
            default=2,
            description="Maximum relationship hops in graph traversal (2 catches transitive supersession A->B->C)"
        )
        llm_temperature: float = Field(
            default=0.2, 
            description="LLM generation temperature (0.0 to 1.0)"
        )
        max_context_chunks: int = Field(
            default=8, 
            description="Maximum context chunks allowed in prompt template"
        )
        llm_max_tokens: int = Field(
            default=DEFAULT_LLM_MAX_TOKENS,
            description="Maximum tokens for LLM generation"
        )
        llm_streaming: bool = Field(
            default=True,
            description="Stream response tokens dynamically or yield the full answer at once (safer for network drops)"
        )

        # Agent Config
        agent_enabled: bool = Field(
            default=os.environ.get("AGENT_ENABLED", "false").lower() == "true",
            description="Use the LangGraph ReAct agent instead of the static RAG flow"
        )
        agent_max_iterations: int = Field(
            default=int(os.environ.get("AGENT_MAX_ITERATIONS", "10")),
            description="Maximum agent tool-calling iterations"
        )
        web_search_provider: str = Field(
            default=os.environ.get("WEB_SEARCH_PROVIDER", "none"),
            description="Web search provider ('exa' or 'none')"
        )
        exa_api_key: str = Field(
            default=os.environ.get("EXA_API_KEY", ""),
            description="Exa API key"
        )

    def __init__(self):
        self.type = "pipe"
        self.id = "vietlegal_rag"
        self.name = "VLGR ⚖️"
        self.valves = self.Valves()
        self._services = None
        self._services_fingerprint = None
        self._lock = threading.Lock()
        
        # Pre-warm services in a background thread to load the heavy embedding model
        # and prevent SSE timeouts on the very first user query.
        threading.Thread(target=self._prewarm_services, daemon=True).start()

    def _prewarm_services(self):
        try:
            logger.info("Pre-warming VietLegal RAG services in background...")
            self._get_services()
            logger.info("Pre-warming services completed successfully.")
        except Exception as e:
            logger.warning(f"Background pre-warming services failed: {e}")


    def _get_services(self):
        """Thread-safe lazy initialization keyed by the active Valves."""
        fingerprint = self._valves_fingerprint()
        if self._services is None or self._services_fingerprint != fingerprint:
            with self._lock:
                if self._services is None or self._services_fingerprint != fingerprint:
                    from vietlegal_rag import build_services
                    logger.info("Initializing VietLegal RAG services dependency injection...")
                    self._services = build_services(self.valves)
                    self._services_fingerprint = fingerprint
        return self._services

    def _valves_fingerprint(self) -> tuple[tuple[str, Any], ...]:
        """Return a stable, comparable snapshot of the current Valves."""
        try:
            values = self.valves.model_dump()
        except AttributeError:
            values = self.valves.dict()
        return tuple(sorted(values.items()))

    async def _stream_sync_generator(
        self,
        answer_stream,
        drain_status_queue: Callable[[], Awaitable[None]],
        *,
        llm_streaming: bool,
    ) -> AsyncGenerator[str, None]:
        """Bridge a blocking sync token generator into the async SSE loop."""
        loop = asyncio.get_running_loop()
        output_queue: asyncio.Queue[Any] = asyncio.Queue()

        def _worker() -> None:
            try:
                if llm_streaming:
                    for token in answer_stream:
                        loop.call_soon_threadsafe(output_queue.put_nowait, token)
                else:
                    full_text = []
                    for token in answer_stream:
                        full_text.append(str(token))
                    loop.call_soon_threadsafe(output_queue.put_nowait, "".join(full_text))
            except Exception as exc:
                loop.call_soon_threadsafe(output_queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(output_queue.put_nowait, _STREAM_DONE)

        worker = threading.Thread(
            target=_worker,
            name="vietlegal-rag-stream",
            daemon=True,
        )
        worker.start()

        while True:
            item = await output_queue.get()
            if item is _STREAM_DONE:
                break
            if isinstance(item, Exception):
                raise item
            await drain_status_queue()
            yield str(item)

    def pipes(self) -> list[dict]:
        return [
            {"id": "vietlegal_rag.groq/qwen/qwen3.6-27b", "name": "(Qwen 3.6 27B)"},
            {"id": "vietlegal_rag.groq/qwen/qwen3-32b", "name": "(Qwen 3 32B)"},
            {"id": "vietlegal_rag.ag/claude-opus-4-6-thinking", "name": "(Claude Opus 4.6)"},
            {"id": "vietlegal_rag.ag/gemini-3-flash-agent", "name": "(Gemini 3.5 Flash)"},
            {"id": "vietlegal_rag.gc/gemini-2.5-pro", "name": "(Gemini 2.5 Pro)"},
            {"id": "vietlegal_rag.gemini/gemma-4-31b-it", "name": "(Gemma 4 31B)"},
            {"id": "vietlegal_rag.groq/llama-3.3-70b-versatile", "name": "(Llama 3.3 70B)"}
        ]

    async def pipe(
        self,
        body: dict,
        __user__: dict,
        __event_emitter__: Callable[[dict], Awaitable[None]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Main pipeline execution entrypoint. Handles streaming responses
        back to Open WebUI while sending background status messages.
        """
        # Override llm_model dynamically from the selected model dropdown
        selected_model_id = body.get("model", "vietlegal_rag")
        actual_model = selected_model_id
        has_override = False
        while "." in actual_model:
            parts = actual_model.split(".", 1)
            if parts[0] == self.id:
                actual_model = parts[1]
                has_override = True
            else:
                break

        if has_override:
            logger.info(f"Overriding RAG LLM model with selected option: {actual_model}")
            # Threaded onto the request below (not written to the shared singleton
            # valve): Pipe serves concurrent users, and the valves fingerprint
            # keys the heavy service cache — mutating it here would race across
            # requests and rebuild every service on each model switch.

        def _message_content_to_text(content: Any) -> str:
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append(str(item.get("text") or ""))
                        elif "content" in item:
                            parts.append(str(item.get("content") or ""))
                return "\n".join(part for part in parts if part).strip()
            return str(content or "")

        messages = body.get("messages") or []
        user_message = _message_content_to_text(messages[-1].get("content")) if messages else ""
        system_prompt = "\n\n".join(
            _message_content_to_text(message.get("content"))
            for message in messages
            if message.get("role") == "system"
        ).strip()

        def _coerce_int_param(name: str, fallback: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
            value = request_params.get(name)
            if value in (None, ""):
                return fallback
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                logger.warning("Ignoring invalid %s value from Advanced Params: %r", name, value)
                return fallback
            if minimum is not None and parsed < minimum:
                return fallback
            if maximum is not None and parsed > maximum:
                return fallback
            return parsed

        request_params = body.get("params") if isinstance(body.get("params"), dict) else {}

        def _coerce_float_param(
            name: str,
            fallback: float,
            *,
            minimum: float | None = None,
            maximum: float | None = None,
        ) -> float:
            value = request_params.get(name)
            if value in (None, ""):
                return fallback
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                logger.warning("Ignoring invalid %s value from Advanced Params: %r", name, value)
                return fallback
            if minimum is not None and parsed < minimum:
                return fallback
            if maximum is not None and parsed > maximum:
                return fallback
            return parsed

        def _coerce_bool_param(name: str, fallback: bool) -> bool:
            value = request_params.get(name)
            if value in (None, ""):
                return fallback
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "on"}:
                    return True
                if lowered in {"false", "0", "no", "off"}:
                    return False
            logger.warning("Ignoring invalid %s value from Advanced Params: %r", name, value)
            return fallback

        def _coerce_choice_param(name: str, fallback: str, choices: set[str]) -> str:
            value = request_params.get(name)
            if value in (None, ""):
                return fallback
            parsed = str(value).strip()
            if parsed in choices:
                return parsed
            logger.warning("Ignoring invalid %s value from Advanced Params: %r", name, value)
            return fallback

        def _coerce_str_param(name: str, fallback: str) -> str:
            value = request_params.get(name)
            if value in (None, ""):
                return fallback
            return str(value)

        retrieval_mode = _coerce_choice_param(
            "retrieval_mode",
            self.valves.retrieval_mode,
            {"dense", "sparse", "hybrid"},
        )
        top_k = _coerce_int_param("top_k", self.valves.top_k, minimum=1, maximum=50)
        rerank_enabled = _coerce_bool_param("rerank_enabled", self.valves.rerank_enabled)
        rerank_model = _coerce_str_param("rerank_model", self.valves.rerank_model)
        graph_enabled = _coerce_bool_param("graph_enabled", self.valves.graph_enabled)
        max_hops = _coerce_int_param("max_hops", self.valves.max_hops, minimum=0, maximum=2)
        llm_temperature = _coerce_float_param(
            "llm_temperature",
            self.valves.llm_temperature,
            minimum=0.0,
            maximum=1.0,
        )
        max_context_chunks = _coerce_int_param(
            "max_context_chunks",
            self.valves.max_context_chunks,
            minimum=1,
            maximum=32,
        )
        llm_max_tokens = _coerce_int_param(
            "llm_max_tokens",
            _coerce_int_param("max_tokens", self.valves.llm_max_tokens, minimum=1),
            minimum=1,
        )
        llm_streaming = _coerce_bool_param("llm_streaming", self.valves.llm_streaming)
        agent_enabled = _coerce_bool_param("agent_enabled", self.valves.agent_enabled)
        status_queue: "queue.Queue[str]" = queue.Queue()

        async def _emit_status(description: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": description, "done": done}}
                )

        async def _drain_status_queue():
            while True:
                try:
                    await _emit_status(status_queue.get_nowait())
                except queue.Empty:
                    return

        # 1. Initialize services dependency graph
        try:
            await _emit_status("Đang kết nối dịch vụ...")
            services = await asyncio.to_thread(self._get_services)
        except Exception as e:
            logger.exception("Failed to initialize backend services dependency tree")
            await _emit_status("Lỗi kết nối hệ thống RAG", done=True)
            yield f"⚠️ Không thể kết nối dịch vụ: {type(e).__name__}. Vui lòng kiểm tra cấu hình trong Valves."
            return

        # 2. Build search request
        from vietlegal_rag.schemas import build_search_request
        from vietlegal_rag.services.retrieval_modes import RetrievalRequest

        search_model = build_search_request(
            query=user_message,
            retrieval_mode=retrieval_mode,
            top_k=top_k,
            rerank_enabled=rerank_enabled,
            rerank_model=rerank_model,
            graph_enabled=graph_enabled,
            max_hops=max_hops,
            llm_temperature=llm_temperature,
            max_context_chunks=max_context_chunks,
            llm_max_tokens=llm_max_tokens,
        )
        request = RetrievalRequest(**search_model.model_dump())
        request.llm.system_prompt = system_prompt
        if has_override:
            request.llm.model = actual_model


        # 3. Stream pipeline phases
        use_agent = bool(agent_enabled and services.agent_service)
        if use_agent:
            await _emit_status("Agent đang phân tích câu hỏi...")
        else:
            await _emit_status("Đang tìm kiếm tài liệu & đồ thị...")
        try:
            if use_agent:
                # AgentService cannot await __event_emitter__ from inside its sync
                # generator, so tool progress arrives via a queue drained below.
                result = services.agent_service.stream_answer(
                    request, on_status=status_queue.put
                )
            else:
                result = services.lightrag_service.stream_answer(request)
            answer_stream = result["answer_stream"]
            citations = result["citations"]
        except Exception:
            logger.exception("Error during retrieval / text processing phase")
            await _emit_status("Lỗi truy vấn", done=True)
            yield "⚠️ Đã xảy ra lỗi khi tìm kiếm ngữ cảnh pháp luật. Vui lòng thử lại sau."
            return

        await _emit_status("Đang tổng hợp câu trả lời...")
        
        # 4. Stream response tokens
        try:
            await _drain_status_queue()
            async for token in self._stream_sync_generator(
                answer_stream,
                _drain_status_queue,
                llm_streaming=llm_streaming,
            ):
                yield token
        except Exception:
            logger.exception("LLM token streaming failed")
            await _emit_status("Lỗi tạo câu trả lời", done=True)
            yield "\n⚠️ Đã xảy ra lỗi khi tạo câu trả lời từ mô hình ngôn ngữ."
            return

        # 5. Emit structured citations to Open-WebUI so inline references [1], [2] work interactively.
        # Do not stream a separate legal-basis block into the message body; Open WebUI's
        # Sources list and citation modal are the canonical citation UI.
        if __event_emitter__ and citations:
            from vietlegal_rag.services.citation_formatter import parse_citation, shorten_title
            for citation_index, cite in enumerate(citations, start=1):
                try:
                    parsed = parse_citation(cite.get("citation") or "")
                    section_path = parsed["section_path"]
                    title = cite.get("title") or parsed["title"]
                    
                    label = f"{section_path}, {title}" if section_path else title
                    shortened_label = f"{section_path}, {shorten_title(title)}" if section_path else shorten_title(title)
                    
                    text = cite.get("text") or ""
                    url = cite.get("url")
                    source_id = (
                        cite.get("chunk_id")
                        or parsed.get("chunk_id")
                        or cite.get("doc_id")
                        or cite.get("citation")
                        or f"citation-{citation_index}"
                    )
                    
                    source_data = {
                        "source": {
                            "name": shortened_label,
                            "url": url or None
                        },
                        "document": [text],
                        "metadata": [
                            {
                                "source": f"vietlegal:{citation_index}:{source_id}",
                                "name": label
                            }
                        ]
                    }
                    
                    await __event_emitter__({
                        "type": "citation",
                        "data": source_data
                    })
                except Exception as e:
                    logger.warning(f"Failed to emit citation event: {e}")

        await _emit_status("Hoàn thành", done=True)
