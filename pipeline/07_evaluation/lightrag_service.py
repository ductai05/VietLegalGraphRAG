from __future__ import annotations

from typing import Any, Protocol

from retrieval_modes import RetrievalRequest


class RetrievalService(Protocol):
    def search(self, request: RetrievalRequest) -> list[dict[str, Any]]:
        ...


class GraphRetriever(Protocol):
    def retrieve(
        self,
        query: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> list[dict[str, Any]]:
        ...


class AnswerService(Protocol):
    def answer(
        self,
        query: str,
        contexts: list[dict[str, Any]],
        temperature: float,
    ) -> dict[str, Any]:
        ...


class LightRAGService:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        graph_retriever: GraphRetriever,
        answer_service: AnswerService,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.graph_retriever = graph_retriever
        self.answer_service = answer_service

    def answer(self, request: RetrievalRequest) -> dict[str, Any]:
        retrieval_hits = self.retrieval_service.search(request)
        graph_context: list[dict[str, Any]] = []
        lightrag_enabled = bool(request.graph.enabled and request.graph.use_lightrag)
        lightrag_error = None

        if lightrag_enabled:
            try:
                graph_context = self.graph_retriever.retrieve(
                    request.query,
                    retrieval_hits,
                    request.graph.max_hops,
                )
            except Exception as exc:
                graph_context = []
                lightrag_enabled = False
                lightrag_error = str(exc)

        contexts = self._merge_contexts(retrieval_hits, graph_context)
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
            "graph_hits": len(graph_context),
        }
        if lightrag_error:
            trace["lightrag_error"] = lightrag_error

        return {
            "answer": answer_payload.get("answer", ""),
            "citations": answer_payload.get("citations", []),
            "retrieval_context": retrieval_hits,
            "graph_context": graph_context,
            "retrieval_trace": trace,
        }

    def _merge_contexts(
        self,
        retrieval_hits: list[dict[str, Any]],
        graph_context: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        contexts: list[dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()

        for hit in retrieval_hits:
            chunk_id = hit.get("chunk_id")
            if chunk_id and chunk_id in seen_chunk_ids:
                continue
            if chunk_id:
                seen_chunk_ids.add(chunk_id)
            contexts.append({"source": "retrieval", **hit})

        for item in graph_context:
            contexts.append({"source": "graph", **item})

        return contexts
