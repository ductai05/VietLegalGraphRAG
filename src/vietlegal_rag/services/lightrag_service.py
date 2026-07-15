from __future__ import annotations

import time
from typing import Any, Protocol

from answer_service import ExtractiveAnswerService
from context_assembler import ContextAssembler
from contracts import AnswerContext, GraphContext, RetrievalHit
from retrieval_modes import RetrievalRequest


class RetrievalService(Protocol):
    def search(self, request: RetrievalRequest) -> list[RetrievalHit]:
        ...


class GraphRetriever(Protocol):
    enabled: bool

    def retrieve(
        self,
        query: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext:
        ...

    def get_version_chain(self, doc_id: str) -> list[dict[str, Any]]:
        ...

    def retrieve_chunk_context(
        self,
        doc_id: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext:
        ...


class AnswerService(Protocol):
    def answer(self, query: str, contexts: list[Any], temperature: float) -> dict[str, Any]:
        ...


class LightRAGService:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        graph_retriever: GraphRetriever,
        answer_service: AnswerService,
        context_assembler: ContextAssembler | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.graph_retriever = graph_retriever
        self.answer_service = answer_service
        self.context_assembler = context_assembler or ContextAssembler()

    def answer(self, request: RetrievalRequest) -> dict[str, Any]:
        started = time.perf_counter()
        retrieval_hits = self.retrieval_service.search(request)
        retrieval_done = time.perf_counter()
        graph_context: GraphContext | None = None
        graph_payload: dict[str, Any] = {}
        graph_runtime_enabled = bool(getattr(self.graph_retriever, "enabled", True))
        lightrag_enabled = bool(
            request.graph.enabled
            and request.graph.use_lightrag
            and graph_runtime_enabled
        )
        lightrag_error = None

        if lightrag_enabled:
            try:
                graph_context = self.graph_retriever.retrieve(
                    request.query,
                    [hit.to_dict() for hit in retrieval_hits],
                    request.graph.max_hops,
                    auto_depth=request.graph.auto_depth,
                )
                graph_payload = graph_context.to_dict()
            except Exception:
                lightrag_enabled = False
                lightrag_error = "graph.retrieval_failed"
        graph_done = time.perf_counter()

        contexts = self.context_assembler.merge(retrieval_hits, graph_context)
        contexts = self._limit_contexts(
            contexts,
            graph_context,
            request.llm.max_context_chunks,
        )
        graph_chunks_used = sum(1 for context in contexts if context.source == "graph")
        answer_error = None
        try:
            answer_payload = self.answer_service.answer(
                request.query,
                contexts,
                request.llm.temperature,
            )
        except Exception:
            answer_error = "llm.answer_failed"
            answer_payload = ExtractiveAnswerService().answer(
                request.query,
                contexts,
                request.llm.temperature,
            )
        answer_done = time.perf_counter()

        trace = {
            "retrieval_mode": request.retrieval_mode,
            "execution_mode": request.execution_mode,
            "reranked": request.rerank.enabled,
            "temperature": request.llm.temperature,
            "graph_enabled": request.graph.enabled,
            "lightrag_enabled": lightrag_enabled,
            "retrieval_hits": len(retrieval_hits),
            "graph_hits": len(graph_context.related_chunks) if graph_context else 0,
            "graph_chunks_used": graph_chunks_used,
            "latency_ms": {
                "retrieval": round((retrieval_done - started) * 1000, 3),
                "graph": round((graph_done - retrieval_done) * 1000, 3),
                "answer": round((answer_done - graph_done) * 1000, 3),
                "total": round((answer_done - started) * 1000, 3),
            },
        }
        if lightrag_error:
            trace["lightrag_error"] = lightrag_error
        if answer_error:
            trace["answer_error"] = answer_error

        # Include document resolution info in trace.
        resolved = self.context_assembler.last_resolved
        if resolved is not None:
            if resolved.warnings:
                trace["resolution_warnings"] = resolved.warnings
            if resolved.resolutions:
                trace["resolutions"] = [
                    r.to_dict() for r in resolved.resolutions
                ]

        return {
            "answer": answer_payload.get("answer", ""),
            "citations": answer_payload.get("citations", []),
            "retrieval_context": [hit.to_dict() for hit in retrieval_hits],
            "graph_context": graph_payload,
            "retrieval_trace": trace,
        }

    def _limit_contexts(
        self,
        contexts: list[AnswerContext],
        graph_context: GraphContext | None,
        max_context_chunks: int,
    ) -> list[AnswerContext]:
        if max_context_chunks <= 0:
            return []
        limited = contexts[:max_context_chunks]
        if (
            graph_context is None
            or not graph_context.related_chunks
            or any(context.source == "graph" for context in limited)
        ):
            return limited

        first_graph = next(
            (context for context in contexts if context.source == "graph"),
            None,
        )
        if first_graph is None:
            return limited
        if max_context_chunks == 1:
            return [first_graph]
        return [*limited[: max_context_chunks - 1], first_graph]

    def stream_answer(self, request: RetrievalRequest) -> dict[str, Any]:
        started = time.perf_counter()
        retrieval_hits = self.retrieval_service.search(request)
        retrieval_done = time.perf_counter()
        graph_context: GraphContext | None = None
        graph_payload: dict[str, Any] = {}
        graph_runtime_enabled = bool(getattr(self.graph_retriever, "enabled", True))
        lightrag_enabled = bool(
            request.graph.enabled
            and request.graph.use_lightrag
            and graph_runtime_enabled
        )
        lightrag_error = None

        if lightrag_enabled:
            try:
                graph_context = self.graph_retriever.retrieve(
                    request.query,
                    [hit.to_dict() for hit in retrieval_hits],
                    request.graph.max_hops,
                    auto_depth=request.graph.auto_depth,
                )
                graph_payload = graph_context.to_dict()
            except Exception:
                lightrag_enabled = False
                lightrag_error = "graph.retrieval_failed"
        graph_done = time.perf_counter()

        contexts = self.context_assembler.merge(retrieval_hits, graph_context)
        contexts = self._limit_contexts(
            contexts,
            graph_context,
            request.llm.max_context_chunks,
        )
        graph_chunks_used = sum(1 for context in contexts if context.source == "graph")
        
        try:
            stream = self.answer_service.stream_answer(
                request.query,
                contexts,
                request.llm.temperature,
            )
        except Exception:
            stream = ExtractiveAnswerService().stream_answer(
                request.query,
                contexts,
                request.llm.temperature,
            )

        trace = {
            "retrieval_mode": request.retrieval_mode,
            "execution_mode": request.execution_mode,
            "reranked": request.rerank.enabled,
            "temperature": request.llm.temperature,
            "graph_enabled": request.graph.enabled,
            "lightrag_enabled": lightrag_enabled,
            "retrieval_hits": len(retrieval_hits),
            "graph_hits": len(graph_context.related_chunks) if graph_context else 0,
            "graph_chunks_used": graph_chunks_used,
        }
        if lightrag_error:
            trace["lightrag_error"] = lightrag_error

        resolved = self.context_assembler.last_resolved
        if resolved is not None:
            if resolved.warnings:
                trace["resolution_warnings"] = resolved.warnings
            if resolved.resolutions:
                trace["resolutions"] = [
                    r.to_dict() for r in resolved.resolutions
                ]

        citations = [
            {
                "chunk_id": context.chunk_id,
                "doc_id": context.doc_id,
                "title": context.title,
                "citation": context.citation,
            }
            for context in contexts
        ]

        return {
            "answer_stream": stream,
            "citations": citations,
            "retrieval_context": [hit.to_dict() for hit in retrieval_hits],
            "graph_context": graph_payload,
            "retrieval_trace": trace,
        }

