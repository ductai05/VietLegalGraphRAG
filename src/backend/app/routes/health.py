from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "degraded",
        "elasticsearch": "not_checked",
        "neo4j": "not_checked",
        "llm": "mock",
    }
