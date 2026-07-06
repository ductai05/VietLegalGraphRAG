from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from dependencies import RuntimeServices, get_runtime_services
from retrieval_modes import RetrievalRequest
from schemas import SearchRequestModel

router = APIRouter()


@router.post("/search")
def search(
    request: SearchRequestModel,
    runtime: RuntimeServices = Depends(get_runtime_services),
) -> dict:
    started = time.perf_counter()
    retrieval_request = RetrievalRequest(**request.model_dump())
    hits = runtime.retrieval_service.search(retrieval_request)
    return {
        "query": retrieval_request.query,
        "retrieval_mode": retrieval_request.retrieval_mode,
        "execution_mode": retrieval_request.execution_mode,
        "latency_ms": _elapsed_ms(started),
        "results": [hit.to_dict() for hit in hits],
        "warnings": runtime.warnings,
        "runtime": runtime.status,
    }


@router.post("/answer")
def answer(
    request: SearchRequestModel,
    runtime: RuntimeServices = Depends(get_runtime_services),
) -> dict:
    """Return answer, citations, retrieval context, graph context, and trace.

    The ``include_trace`` request field is reserved for forward compatibility
    only. During the MVP, ``retrieval_trace`` is always included in the
    response regardless of the field value.
    """
    started = time.perf_counter()
    retrieval_request = RetrievalRequest(**request.model_dump())
    payload = runtime.lightrag_service.answer(retrieval_request)
    trace = payload.setdefault("retrieval_trace", {})
    trace["runtime"] = runtime.status.get("runtime", "unknown")
    trace["services"] = runtime.status
    payload["warnings"] = runtime.warnings
    payload["latency_ms"] = _elapsed_ms(started)
    return payload


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
