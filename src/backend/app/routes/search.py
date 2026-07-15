from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import json

from config import get_settings
from dependencies import RuntimeServices, get_runtime_services
from retrieval_modes import RetrievalRequest
from schemas import SearchRequestModel

router = APIRouter()


def _ensure_rerank_model_allowed(request: SearchRequestModel) -> None:
    """Reject client-selected rerank models unless allowlisted by config."""
    if not request.rerank.enabled:
        return
    allowlist = get_settings().rerank_model_allowlist
    if "*" in allowlist or request.rerank.model in allowlist:
        return
    raise HTTPException(
        status_code=422,
        detail={
            "error": "validation_error",
            "detail": "rerank.model is not in the configured allowlist",
            "allowed": sorted(allowlist),
        },
    )


@router.post("/search")
def search(
    request: SearchRequestModel,
    runtime: RuntimeServices = Depends(get_runtime_services),
) -> dict:
    _ensure_rerank_model_allowed(request)
    started = time.perf_counter()
    retrieval_request = RetrievalRequest(**request.model_dump())
    hits = runtime.retrieval_service.search(retrieval_request)
    
    runtime_info = dict(runtime.status)
    if retrieval_request.rerank.enabled:
        active_provider = (retrieval_request.rerank.provider or get_settings().rerank_provider).lower()
    else:
        active_provider = "noop"
    runtime_info["reranker"] = active_provider

    if retrieval_request.rerank.enabled and not any("rerank" in hit.scores for hit in hits):
        warn_key = f"reranker.{active_provider}_api_failed"
        if warn_key not in runtime.warnings:
            runtime.warnings.append(warn_key)

    return {
        "query": retrieval_request.query,
        "retrieval_mode": retrieval_request.retrieval_mode,
        "execution_mode": retrieval_request.execution_mode,
        "latency_ms": _elapsed_ms(started),
        "results": [hit.to_dict() for hit in hits],
        "warnings": runtime.warnings,
        "runtime": runtime_info,
    }


@router.post("/answer", response_model=None)
def answer(
    request: SearchRequestModel,
    runtime: RuntimeServices = Depends(get_runtime_services),
) -> Any:
    """Return answer, citations, retrieval context, graph context, and trace.

    The ``include_trace`` request field is reserved for forward compatibility
    only. During the MVP, ``retrieval_trace`` is always included in the
    response regardless of the field value.
    """
    _ensure_rerank_model_allowed(request)
    started = time.perf_counter()
    retrieval_request = RetrievalRequest(**request.model_dump())

    if request.stream:
        def event_generator():
            generator = runtime.lightrag_service.answer_stream(retrieval_request)
            for chunk in generator:
                if chunk["type"] == "metadata":
                    trace = chunk["retrieval_trace"]
                    trace["runtime"] = runtime.status.get("runtime", "unknown")
                    
                    runtime_info = dict(runtime.status)
                    if retrieval_request.rerank.enabled:
                        active_provider = (retrieval_request.rerank.provider or get_settings().rerank_provider).lower()
                    else:
                        active_provider = "noop"
                    runtime_info["reranker"] = active_provider
                    trace["services"] = runtime_info
                    
                    if retrieval_request.rerank.enabled:
                        context_hits = chunk.get("retrieval_context", [])
                        rerank_succeeded = any("rerank" in hit.get("scores", {}) for hit in context_hits)
                        if not rerank_succeeded:
                            active_provider = (retrieval_request.rerank.provider or get_settings().rerank_provider).lower()
                            warn_key = f"reranker.{active_provider}_api_failed"
                            if warn_key not in runtime.warnings:
                                runtime.warnings.append(warn_key)
                            trace["reranked"] = False
                            trace["rerank_error"] = f"{active_provider}.api_failed"
                    
                    chunk["warnings"] = runtime.warnings
                elif chunk["type"] == "done":
                    # Update done trace with services info
                    trace = chunk["retrieval_trace"]
                    trace["runtime"] = runtime.status.get("runtime", "unknown")
                    
                    runtime_info = dict(runtime.status)
                    if retrieval_request.rerank.enabled:
                        active_provider = (retrieval_request.rerank.provider or get_settings().rerank_provider).lower()
                    else:
                        active_provider = "noop"
                    runtime_info["reranker"] = active_provider
                    trace["services"] = runtime_info
                    chunk["warnings"] = runtime.warnings

                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    payload = runtime.lightrag_service.answer(retrieval_request)
    trace = payload.setdefault("retrieval_trace", {})
    trace["runtime"] = runtime.status.get("runtime", "unknown")
    
    runtime_info = dict(runtime.status)
    if retrieval_request.rerank.enabled:
        active_provider = (retrieval_request.rerank.provider or get_settings().rerank_provider).lower()
    else:
        active_provider = "noop"
    runtime_info["reranker"] = active_provider
    trace["services"] = runtime_info
    
    if retrieval_request.rerank.enabled:
        context_hits = payload.get("retrieval_context", [])
        rerank_succeeded = any("rerank" in hit.get("scores", {}) for hit in context_hits)
        if not rerank_succeeded:
            active_provider = (retrieval_request.rerank.provider or get_settings().rerank_provider).lower()
            warn_key = f"reranker.{active_provider}_api_failed"
            if warn_key not in runtime.warnings:
                runtime.warnings.append(warn_key)
            trace["reranked"] = False
            trace["rerank_error"] = f"{active_provider}.api_failed"

    payload["warnings"] = runtime.warnings
    payload["latency_ms"] = _elapsed_ms(started)
    return payload


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
