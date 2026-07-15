import os
import sys
import logging
import threading
from typing import Generator, Callable, Awaitable, AsyncGenerator, Any
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vietlegal_rag.pipe")

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
            default=1, 
            description="Maximum relationship hops in graph traversal"
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
            default=2048,
            description="Maximum tokens for LLM generation"
        )

    def __init__(self):
        self.type = "pipe"
        self.id = "vietlegal_rag"
        self.name = "VietLegal RAG"
        self.valves = self.Valves()
        self._services = None
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
        """Thread-safe lazy initialization of services."""
        if self._services is None:
            with self._lock:
                if self._services is None:
                    from vietlegal_rag import build_services
                    logger.info("Initializing VietLegal RAG services dependency injection...")
                    self._services = build_services(self.valves)
        return self._services

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
        user_id = __user__.get("id", "anonymous")
        user_message = body["messages"][-1]["content"]

        async def _emit_status(description: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__(
                    {"type": "status", "data": {"description": description, "done": done}}
                )

        # 1. Initialize services dependency graph
        try:
            await _emit_status("Đang kết nối dịch vụ...")
            services = self._get_services()
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
            retrieval_mode=self.valves.retrieval_mode,
            top_k=self.valves.top_k,
            rerank_enabled=self.valves.rerank_enabled,
            rerank_model=self.valves.rerank_model,
            graph_enabled=self.valves.graph_enabled,
            max_hops=self.valves.max_hops,
            llm_temperature=self.valves.llm_temperature,
            max_context_chunks=self.valves.max_context_chunks,
            llm_max_tokens=self.valves.llm_max_tokens,
        )
        request = RetrievalRequest(**search_model.model_dump())


        # 3. Stream pipeline phases
        await _emit_status("Đang tìm kiếm tài liệu & đồ thị...")
        try:
            # We call services.lightrag_service.stream_answer directly
            result = services.lightrag_service.stream_answer(request)
            answer_stream = result["answer_stream"]
            citations = result["citations"]
        except Exception as e:
            logger.exception("Error during retrieval / text processing phase")
            await _emit_status("Lỗi truy vấn", done=True)
            yield "⚠️ Đã xảy ra lỗi khi tìm kiếm ngữ cảnh pháp luật. Vui lòng thử lại sau."
            return

        await _emit_status("Đang tổng hợp câu trả lời...")
        
        # 4. Stream response tokens
        try:
            for token in answer_stream:
                yield token
        except Exception as e:
            logger.exception("LLM token streaming failed")
            await _emit_status("Lỗi tạo câu trả lời", done=True)
            yield "\n⚠️ Đã xảy ra lỗi khi tạo câu trả lời từ mô hình ngôn ngữ."
            return

        # 5. Yield citations at the end of the answer
        if citations:
            citations_md = "\n\n---\n**📚 Căn cứ pháp lý:**\n"
            seen = set()
            idx = 1
            for cite in citations:
                citation_str = cite.get("citation", "")
                title_str = cite.get("title", "Tài liệu liên quan")
                if not citation_str:
                    continue
                # Remove duplicate citations to keep list clean
                dedup_key = (title_str, citation_str)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                citations_md += f"- **[{idx}]** {title_str} ({citation_str})\n"
                idx += 1
            yield citations_md

        await _emit_status("Hoàn thành", done=True)
