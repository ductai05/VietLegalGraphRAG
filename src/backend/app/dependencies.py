# ruff: noqa: E402
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SERVICES_DIR = _BACKEND_ROOT / "services"
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))

from answer_service import ExtractiveAnswerService, OpenAICompatibleAnswerService
from config import Settings, get_settings
from context_assembler import ContextAssembler
from contracts import GraphContext, RetrievalHit
from document_resolver import DocumentResolver
from elasticsearch_retriever import (
    ElasticsearchDenseRetriever,
    ElasticsearchGraphChunkFetcher,
    ElasticsearchTextRetriever,
)
from embedding_service import LocalHFEmbedder, LocalONNXEmbedder
from graph_retriever import GraphRetriever
from lightrag_service import LightRAGService
from rerank_service import NoopReranker, VoyageReranker, JinaReranker, RoutingReranker
from retrieval_modes import RetrievalRequest
from retrieval_service import RetrievalService


class DemoRetrievalService:
    def search(self, request: RetrievalRequest) -> list[RetrievalHit]:
        return [
            RetrievalHit(
                rank=1,
                chunk_id="chunk:demo:000001",
                doc_id="demo",
                title="Văn bản demo",
                document_number="01/2026/QH",
                legal_type="Luật",
                effect_status="Còn hiệu lực",
                section_path="Điều 1",
                text="Nội dung demo cho câu hỏi.",
                scores={"fallback": 1.0},
                citation="Văn bản demo, Điều 1",
            )
        ][: request.top_k]


class NoopGraphRetriever:
    enabled = False

    def retrieve(
        self,
        query: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext:
        return GraphContext(center=None, query_intent="general")

    def get_document_neighbors(
        self,
        doc_id: str,
        relations: list[str] | None = None,
        depth: int = 1,
    ) -> GraphContext:
        return GraphContext(center=None, query_intent="general")

    def get_version_chain(self, doc_id: str) -> list[dict[str, Any]]:
        return []

    def retrieve_chunk_context(
        self,
        doc_id: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext:
        return GraphContext(center=None, query_intent="general")


@dataclass(frozen=True)
class RuntimeServices:
    retrieval_service: Any
    graph_retriever: Any
    answer_service: Any
    lightrag_service: LightRAGService
    ocr_service: Any
    status: dict[str, str]
    warnings: list[str]


@lru_cache(maxsize=1)
def get_runtime_services() -> RuntimeServices:
    settings = get_settings()
    warnings: list[str] = []
    status: dict[str, str] = {}

    ocr_service = _build_ocr_service(settings, warnings, status)
    retrieval_service = _build_retrieval_service(settings, warnings, status)
    graph_retriever = _build_graph_retriever(settings, warnings, status)
    answer_service = _build_answer_service(settings, warnings, status)

    # Build the DocumentResolver with a version-chain callback backed by
    # the graph retriever.  NoopGraphRetriever.get_version_chain returns []
    # so the resolver gracefully degrades when Neo4j is unavailable.
    version_chain_fn = getattr(graph_retriever, "get_version_chain", None)
    document_resolver = DocumentResolver(version_chain_fn=version_chain_fn)

    lightrag_service = LightRAGService(
        retrieval_service=retrieval_service,
        graph_retriever=graph_retriever,
        answer_service=answer_service,
        context_assembler=ContextAssembler(document_resolver=document_resolver),
    )
    status["runtime"] = "fallback" if "runtime.fallback" in warnings else "configured"
    return RuntimeServices(
        retrieval_service=retrieval_service,
        graph_retriever=graph_retriever,
        answer_service=answer_service,
        lightrag_service=lightrag_service,
        ocr_service=ocr_service,
        status=status,
        warnings=warnings,
    )


def _build_retrieval_service(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
) -> Any:
    if not _elasticsearch_is_configured(settings):
        warnings.append("runtime.fallback")
        warnings.append("elasticsearch.not_configured")
        status["elasticsearch"] = "fallback"
        status["embedding"] = "disabled"
        status["dense"] = "disabled"
        status["dense_retrieval"] = "disabled"
        status["reranker"] = "noop"
        return DemoRetrievalService()

    try:
        from elasticsearch import Elasticsearch

        kwargs: dict[str, Any] = {
            "request_timeout": settings.elasticsearch_request_timeout,
            "verify_certs": settings.elasticsearch_verify_certs,
        }
        if settings.elasticsearch_api_key:
            kwargs["api_key"] = settings.elasticsearch_api_key
        elif settings.elasticsearch_username and settings.elasticsearch_password:
            kwargs["basic_auth"] = (
                settings.elasticsearch_username,
                settings.elasticsearch_password,
            )
        client = Elasticsearch(settings.elasticsearch_url, **kwargs)
        if not client.ping():
            raise RuntimeError("elasticsearch unreachable")
        index = settings.elasticsearch_alias or settings.elasticsearch_index
        retriever = ElasticsearchTextRetriever(client, index=index)
        status["elasticsearch"] = "configured"
        dense_retriever = _build_dense_retriever(
            settings, warnings, status, client=client, index=index
        )
        if dense_retriever is None:
            warnings.append("dense.not_configured")
        dense_status = "configured" if dense_retriever else "disabled"
        status["dense"] = dense_status
        status["dense_retrieval"] = dense_status
        return RetrievalService(
            dense_retriever=dense_retriever,
            sparse_retriever=retriever,
            reranker=_build_reranker(settings, warnings, status),
        )
    except Exception:
        if not settings.runtime_fallback_enabled:
            raise
        # Warning codes are client-visible: never include exception details.
        warnings.append("runtime.fallback")
        warnings.append("elasticsearch.init_failed")
        status["elasticsearch"] = "fallback"
        status["embedding"] = "disabled"
        status["dense"] = "disabled"
        status["dense_retrieval"] = "disabled"
        status["reranker"] = "noop"
        return DemoRetrievalService()


def _build_embedder(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
) -> Any:
    provider = settings.embedding_provider.strip().lower()
    dims = settings.embedding_dims or None

    # ONNX path: no torch required.
    if provider == "onnx":
        return _build_onnx_embedder(settings, warnings, status, dims)

    # Default: PyTorch/HuggingFace path.
    return _build_hf_embedder(settings, warnings, status, dims)


def _build_onnx_embedder(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
    dims: int | None,
) -> Any:
    model_path = settings.embedding_onnx_model_path
    tokenizer_path = settings.embedding_onnx_tokenizer_path
    if not model_path or not tokenizer_path:
        warnings.append("embedding.onnx_path_missing")
        status["embedding"] = "disabled"
        return None
    try:
        embedder: Any = LocalONNXEmbedder(
            model_path=model_path,
            tokenizer_path=tokenizer_path,
            dims=dims,
            max_length=settings.embedding_max_length,
        )
        status["embedding"] = "onnx"
        return embedder
    except Exception:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append("embedding.init_failed")
        status["embedding"] = "disabled"
        return None


def _build_hf_embedder(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
    dims: int | None,
) -> Any:
    try:
        embedder: Any = LocalHFEmbedder(
            model=settings.embedding_model,
            dims=dims,
            device=settings.embedding_device,
            cache_dir=settings.embedding_cache_dir,
            max_length=settings.embedding_max_length,
        )
        status["embedding"] = "local-hf"
        return embedder
    except Exception:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append("embedding.init_failed")
        status["embedding"] = "disabled"
        return None


def _build_dense_retriever(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
    *,
    client: Any,
    index: str,
) -> Any:
    if settings.dense_num_candidates_factor_invalid:
        warnings.append("config.dense_num_candidates_factor_invalid")
    if settings.dense_min_num_candidates_invalid:
        warnings.append("config.dense_min_num_candidates_invalid")
    embedder = _build_embedder(settings, warnings, status)
    if embedder is None:
        return None
    try:
        index_dims = _mapping_vector_dims(client, index)
    except Exception:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append("dense.mapping_check_failed")
        status["embedding"] = "disabled"
        status["dense_retrieval"] = "disabled"
        return None
    if index_dims is None:
        warnings.append("dense.vector_mapping_missing")
        status["embedding"] = "disabled"
        status["dense_retrieval"] = "disabled"
        return None
    if embedder.dims is not None and embedder.dims != index_dims:
        warnings.append("dense.dim_mismatch")
        status["embedding"] = "disabled"
        status["dense_retrieval"] = "disabled"
        return None
    return ElasticsearchDenseRetriever(
        client,
        index=index,
        embedder=embedder,
        num_candidates_factor=settings.dense_num_candidates_factor,
        min_num_candidates=settings.dense_min_num_candidates,
    )


def _mapping_vector_dims(client: Any, index: str) -> int | None:
    """Return dims of the `vector` dense_vector field, or None if absent."""
    mapping = client.indices.get_mapping(index=index)
    for index_mapping in dict(mapping).values():
        properties = (index_mapping.get("mappings") or {}).get("properties") or {}
        vector = properties.get("vector") or {}
        if vector.get("type") == "dense_vector":
            dims = vector.get("dims")
            return int(dims) if dims is not None else None
    return None


def _build_reranker(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
) -> Any:
    configured_rerankers = []

    # Build Voyage Reranker if configured
    voyage_reranker = NoopReranker()
    if settings.voyage_api_key:
        try:
            import voyageai
            voyage_reranker = VoyageReranker(
                client=voyageai.Client(api_key=settings.voyage_api_key),
                model=settings.rerank_model,
            )
            configured_rerankers.append("voyage")
        except Exception:
            warnings.append("reranker.voyage_init_failed")
    else:
        warnings.append("reranker.voyage_not_configured")

    # Build Jina Reranker if configured
    jina_reranker = NoopReranker()
    if settings.jina_api_key:
        jina_reranker = JinaReranker(
            api_key=settings.jina_api_key,
            model=settings.rerank_model,
        )
        configured_rerankers.append("jina")
    else:
        warnings.append("reranker.jina_not_configured")

    if configured_rerankers:
        status["reranker"] = ", ".join(configured_rerankers)
    else:
        status["reranker"] = "noop"

    return RoutingReranker(
        voyage_reranker=voyage_reranker,
        jina_reranker=jina_reranker,
        default_provider=settings.rerank_provider,
    )


def _build_graph_retriever(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
) -> Any:
    if not settings.neo4j_password:
        warnings.append("neo4j.not_configured")
        status["neo4j"] = "disabled"
        return NoopGraphRetriever()
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        status["neo4j"] = "configured"
        return GraphRetriever(
            driver,
            database=settings.neo4j_database,
            chunk_fetcher=_build_graph_chunk_fetcher(settings, warnings),
        )
    except Exception:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append("neo4j.init_failed")
        status["neo4j"] = "disabled"
        return NoopGraphRetriever()


def _build_graph_chunk_fetcher(
    settings: Settings,
    warnings: list[str],
) -> Any:
    if not _elasticsearch_is_configured(settings):
        return None
    try:
        from elasticsearch import Elasticsearch

        kwargs: dict[str, Any] = {
            "request_timeout": settings.elasticsearch_request_timeout,
            "verify_certs": settings.elasticsearch_verify_certs,
        }
        if settings.elasticsearch_api_key:
            kwargs["api_key"] = settings.elasticsearch_api_key
        elif settings.elasticsearch_username and settings.elasticsearch_password:
            kwargs["basic_auth"] = (
                settings.elasticsearch_username,
                settings.elasticsearch_password,
            )
        client = Elasticsearch(settings.elasticsearch_url, **kwargs)
        index = settings.elasticsearch_alias or settings.elasticsearch_index
        return ElasticsearchGraphChunkFetcher(client, index=index)
    except Exception:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append("graph.chunk_fetcher_unavailable")
        return None


def _build_answer_service(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
) -> Any:
    if settings.llm_provider.lower() != "openai-compatible":
        status["llm"] = "extractive"
        return ExtractiveAnswerService()
    if not settings.llm_api_key:
        warnings.append("llm.not_configured")
        status["llm"] = "extractive"
        return ExtractiveAnswerService()
    try:
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": settings.llm_api_key}
        if settings.llm_base_url:
            kwargs["base_url"] = settings.llm_base_url
        status["llm"] = "openai-compatible"
        return OpenAICompatibleAnswerService(
            client=OpenAI(**kwargs),
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
        )
    except Exception:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append("llm.init_failed")
        status["llm"] = "extractive"
        return ExtractiveAnswerService()


def _elasticsearch_is_configured(settings: Settings) -> bool:
    explicitly_configured = "ELASTICSEARCH_URL" in os.environ
    has_auth = bool(
        settings.elasticsearch_api_key
        or (settings.elasticsearch_username and settings.elasticsearch_password)
    )
    return explicitly_configured or has_auth


def _build_ocr_service(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
) -> Any:
    from ocr_service import GoogleVisionOcrService, NoopOcrService

    provider = settings.ocr_provider.strip().lower()
    if provider in {"", "none"}:
        status["ocr"] = "disabled"
        return NoopOcrService()
    if provider == "google":
        if settings.ocr_config_invalid:
            warnings.append("config.ocr_max_file_mb_invalid")
        try:
            service = GoogleVisionOcrService(language_hints=settings.ocr_language_hints)
            status["ocr"] = "google"
            return service
        except Exception:
            if not settings.runtime_fallback_enabled:
                raise
            warnings.append("ocr.init_failed")
            status["ocr"] = "disabled"
            return NoopOcrService()
    warnings.append("ocr.unknown_provider")
    status["ocr"] = "disabled"
    return NoopOcrService()
