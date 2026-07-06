from __future__ import annotations

from fastapi import APIRouter, Depends

from dependencies import RuntimeServices, get_runtime_services

router = APIRouter()


@router.get("/health")
def health(runtime: RuntimeServices = Depends(get_runtime_services)) -> dict[str, str]:
    status = "ok"
    if any(value in {"fallback", "disabled", "extractive", "noop"} for value in runtime.status.values()):
        status = "degraded"
    return {
        "status": status,
        "elasticsearch": runtime.status.get("elasticsearch", "unknown"),
        "neo4j": runtime.status.get("neo4j", "unknown"),
        "llm": runtime.status.get("llm", "unknown"),
        "reranker": runtime.status.get("reranker", "unknown"),
        "runtime": runtime.status.get("runtime", "unknown"),
    }
