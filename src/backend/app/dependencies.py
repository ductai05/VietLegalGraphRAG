from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from answer_service import ExtractiveAnswerService, OpenAICompatibleAnswerService
from config import Settings, get_settings
from context_assembler import ContextAssembler
from contracts import GraphContext, RetrievalHit
from elasticsearch_retriever import ElasticsearchTextRetriever
from graph_retriever import GraphRetriever
from lightrag_service import LightRAGService
from rerank_service import NoopReranker, VoyageReranker
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


@dataclass(frozen=True)
class RuntimeServices:
    retrieval_service: Any
    graph_retriever: Any
    answer_service: Any
    lightrag_service: LightRAGService
    status: dict[str, str]
    warnings: list[str]


@lru_cache(maxsize=1)
def get_runtime_services() -> RuntimeServices:
    settings = get_settings()
    warnings: list[str] = []
    status: dict[str, str] = {}

    retrieval_service = _build_retrieval_service(settings, warnings, status)
    graph_retriever = _build_graph_retriever(settings, warnings, status)
    answer_service = _build_answer_service(settings, warnings, status)
    lightrag_service = LightRAGService(
        retrieval_service=retrieval_service,
        graph_retriever=graph_retriever,
        answer_service=answer_service,
        context_assembler=ContextAssembler(),
    )
    status["runtime"] = "fallback" if "runtime.fallback" in warnings else "configured"
    return RuntimeServices(
        retrieval_service=retrieval_service,
        graph_retriever=graph_retriever,
        answer_service=answer_service,
        lightrag_service=lightrag_service,
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
        retriever = ElasticsearchTextRetriever(
            client,
            index=settings.elasticsearch_alias or settings.elasticsearch_index,
        )
        status["elasticsearch"] = "configured"
        warnings.append("dense_vector_query_unavailable")
        return RetrievalService(
            dense_retriever=retriever,
            sparse_retriever=retriever,
            reranker=_build_reranker(settings, warnings, status),
        )
    except Exception as exc:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append("runtime.fallback")
        warnings.append(f"elasticsearch.init_failed:{exc.__class__.__name__}")
        status["elasticsearch"] = "fallback"
        status["reranker"] = "noop"
        return DemoRetrievalService()


def _build_reranker(
    settings: Settings,
    warnings: list[str],
    status: dict[str, str],
) -> Any:
    if settings.rerank_provider.lower() != "voyage":
        status["reranker"] = "noop"
        return NoopReranker()
    if not settings.voyage_api_key:
        warnings.append("reranker.voyage_not_configured")
        status["reranker"] = "noop"
        return NoopReranker()
    try:
        import voyageai

        status["reranker"] = "voyage"
        return VoyageReranker(
            client=voyageai.Client(api_key=settings.voyage_api_key),
            model=settings.rerank_model,
        )
    except Exception as exc:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append(f"reranker.init_failed:{exc.__class__.__name__}")
        status["reranker"] = "noop"
        return NoopReranker()


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
        return GraphRetriever(driver, database=settings.neo4j_database)
    except Exception as exc:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append(f"neo4j.init_failed:{exc.__class__.__name__}")
        status["neo4j"] = "disabled"
        return NoopGraphRetriever()


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
        )
    except Exception as exc:
        if not settings.runtime_fallback_enabled:
            raise
        warnings.append(f"llm.init_failed:{exc.__class__.__name__}")
        status["llm"] = "extractive"
        return ExtractiveAnswerService()


def _elasticsearch_is_configured(settings: Settings) -> bool:
    explicitly_configured = "ELASTICSEARCH_URL" in os.environ
    has_auth = bool(
        settings.elasticsearch_api_key
        or (settings.elasticsearch_username and settings.elasticsearch_password)
    )
    return explicitly_configured or has_auth
