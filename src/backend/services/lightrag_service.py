from __future__ import annotations

from typing import Any, Protocol

from context_assembler import ContextAssembler
from contracts import GraphContext, RetrievalHit
from retrieval_modes import RetrievalRequest


class RetrievalService(Protocol):
    def search(self, request: RetrievalRequest) -> list[RetrievalHit]:
        ...


class GraphRetriever(Protocol):
    def retrieve(
        self,
        query: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext | dict[str, Any]:
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
        retrieval_hits = self.retrieval_service.search(request)
        graph_context: GraphContext | None = None
        graph_payload: dict[str, Any] = {}
        lightrag_enabled = bool(request.graph.enabled and request.graph.use_lightrag)
        lightrag_error = None

        if lightrag_enabled:
            try:
                raw_graph_context = self.graph_retriever.retrieve(
                    request.query,
                    [hit.to_dict() for hit in retrieval_hits],
                    request.graph.max_hops,
                )
                if isinstance(raw_graph_context, GraphContext):
                    graph_context = raw_graph_context
                    graph_payload = graph_context.to_dict()
                else:
                    graph_payload = raw_graph_context
            except Exception as exc:
                lightrag_enabled = False
                lightrag_error = str(exc)

        contexts = self.context_assembler.merge(retrieval_hits, graph_context)
        answer_payload = self.answer_service.answer(
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
        }
        if lightrag_error:
            trace["lightrag_error"] = lightrag_error

        return {
            "answer": answer_payload.get("answer", ""),
            "citations": answer_payload.get("citations", []),
            "retrieval_context": [hit.to_dict() for hit in retrieval_hits],
            "graph_context": graph_payload,
            "retrieval_trace": trace,
        }
