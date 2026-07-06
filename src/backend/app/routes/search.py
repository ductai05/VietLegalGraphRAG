from __future__ import annotations

from fastapi import APIRouter

from dependencies import DemoRetrievalService
from retrieval_modes import RetrievalRequest
from schemas import SearchRequestModel

router = APIRouter()


@router.post("/search")
def search(request: SearchRequestModel) -> dict:
    retrieval_request = RetrievalRequest(**request.model_dump())
    hits = DemoRetrievalService().search(retrieval_request)
    return {
        "query": retrieval_request.query,
        "retrieval_mode": retrieval_request.retrieval_mode,
        "execution_mode": retrieval_request.execution_mode,
        "latency_ms": 0,
        "results": [hit.to_dict() for hit in hits],
        "warnings": ["demo_dependency"],
    }


@router.post("/answer")
def answer(request: SearchRequestModel) -> dict:
    """Return answer, citations, retrieval context, graph context, and trace.

    The ``include_trace`` request field is reserved for forward compatibility
    only.  During the MVP, ``retrieval_trace`` is **always** included in the
    response regardless of the field value.  The frontend MUST expect
    ``retrieval_trace`` to be present.
    """
    retrieval_request = RetrievalRequest(**request.model_dump())
    hits = DemoRetrievalService().search(retrieval_request)
    return {
        "answer": hits[0].text if hits else "Không tìm thấy đủ ngữ cảnh để trả lời.",
        "citations": [{"chunk_id": hit.chunk_id, "doc_id": hit.doc_id, "title": hit.title} for hit in hits],
        "retrieval_context": [hit.to_dict() for hit in hits],
        "graph_context": {},
        "retrieval_trace": {
            "retrieval_mode": retrieval_request.retrieval_mode,
            "execution_mode": retrieval_request.execution_mode,
            "reranked": retrieval_request.rerank.enabled,
            "temperature": retrieval_request.llm.temperature,
            "graph_enabled": retrieval_request.graph.enabled,
            "lightrag_enabled": False,
        },
        "latency_ms": 0,
    }
