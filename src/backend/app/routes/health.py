from __future__ import annotations

from fastapi import APIRouter, Depends

from config import get_settings
from dependencies import RuntimeServices, get_runtime_services

router = APIRouter()


@router.get("/health")
def health(runtime: RuntimeServices = Depends(get_runtime_services)) -> dict[str, str]:
    settings = get_settings()
    degraded = any(
        value in {"fallback", "disabled"} for value in runtime.status.values()
    )
    # "extractive"/"noop" only degrade when a higher provider was configured
    # but could not be initialized; they are valid intended defaults otherwise.
    if (
        runtime.status.get("llm") == "extractive"
        and settings.llm_provider.lower() == "openai-compatible"
    ):
        degraded = True
    if (
        runtime.status.get("reranker") == "noop"
        and settings.rerank_provider.lower() == "voyage"
    ):
        degraded = True
    if (
        runtime.status.get("embedding") == "disabled"
        and settings.embedding_provider.strip().lower() not in {"", "none"}
    ):
        degraded = True
    if (
        runtime.status.get("ocr") == "disabled"
        and settings.ocr_provider.strip().lower() not in {"", "none"}
    ):
        degraded = True
    status = "degraded" if degraded else "ok"
    return {
        "status": status,
        "elasticsearch": runtime.status.get("elasticsearch", "unknown"),
        "neo4j": runtime.status.get("neo4j", "unknown"),
        "llm": runtime.status.get("llm", "unknown"),
        "reranker": runtime.status.get("reranker", "unknown"),
        "embedding": runtime.status.get("embedding", "unknown"),
        "dense_retrieval": runtime.status.get(
            "dense_retrieval",
            runtime.status.get("dense", "unknown"),
        ),
        "runtime": runtime.status.get("runtime", "unknown"),
        "ocr": runtime.status.get("ocr", "unknown"),
    }
