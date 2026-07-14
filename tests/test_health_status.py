from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _client_with_status(
    status: dict[str, str],
    warnings: list[str] | None = None,
) -> TestClient:
    """Hermetic client: fabricated RuntimeServices via dependency_overrides.

    No live Elasticsearch/Neo4j/Voyage/LLM calls are made.
    """
    from dependencies import RuntimeServices, get_runtime_services
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=None,
        status=status,
        warnings=warnings or [],
    )
    app = create_app()
    app.dependency_overrides[get_runtime_services] = lambda: runtime
    return TestClient(app)


def test_health_ok_with_intended_local_defaults(monkeypatch) -> None:
    """noop reranker + extractive LLM are intended defaults, not degradation."""
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")
    from config import get_settings

    get_settings.cache_clear()
    client = _client_with_status(
        {
            "elasticsearch": "configured",
            "reranker": "noop",
            "neo4j": "configured",
            "llm": "extractive",
            "runtime": "configured",
        }
    )
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    get_settings.cache_clear()


def test_health_degraded_when_elasticsearch_falls_back() -> None:
    client = _client_with_status(
        {
            "elasticsearch": "fallback",
            "reranker": "noop",
            "neo4j": "disabled",
            "llm": "extractive",
            "runtime": "fallback",
        }
    )
    response = client.get("/health")
    assert response.json()["status"] == "degraded"


def test_health_degraded_when_configured_voyage_falls_to_noop(monkeypatch) -> None:
    """RERANK_PROVIDER=voyage that ends up noop must be reported as degraded."""
    monkeypatch.setenv("RERANK_PROVIDER", "voyage")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")
    from config import get_settings

    get_settings.cache_clear()
    client = _client_with_status(
        {
            "elasticsearch": "configured",
            "reranker": "noop",
            "llm": "extractive",
            "runtime": "configured",
        }
    )
    response = client.get("/health")
    assert response.json()["status"] == "degraded"
    get_settings.cache_clear()


def test_health_degraded_when_configured_llm_falls_to_extractive(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    from config import get_settings

    get_settings.cache_clear()
    client = _client_with_status(
        {
            "elasticsearch": "configured",
            "reranker": "noop",
            "llm": "extractive",
            "runtime": "configured",
        }
    )
    response = client.get("/health")
    assert response.json()["status"] == "degraded"
    get_settings.cache_clear()


def test_health_exposes_embedding_and_dense_retrieval_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")
    from config import get_settings

    get_settings.cache_clear()
    client = _client_with_status(
        {
            "elasticsearch": "configured",
            "reranker": "noop",
            "neo4j": "configured",
            "llm": "extractive",
            "embedding": "local-hf",
            "dense_retrieval": "configured",
            "runtime": "configured",
        }
    )

    payload = client.get("/health").json()

    assert payload["status"] == "ok"
    assert payload["embedding"] == "local-hf"
    assert payload["dense_retrieval"] == "configured"
    get_settings.cache_clear()


def test_health_exposes_disabled_dense_when_startup_disables_it(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")
    from config import get_settings

    get_settings.cache_clear()
    client = _client_with_status(
        {
            "elasticsearch": "configured",
            "reranker": "noop",
            "neo4j": "configured",
            "llm": "extractive",
            "embedding": "disabled",
            "dense_retrieval": "disabled",
            "runtime": "configured",
        }
    )

    payload = client.get("/health").json()

    assert payload["status"] == "degraded"
    assert payload["embedding"] == "disabled"
    assert payload["dense_retrieval"] == "disabled"
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "warning",
    ["dense.dim_mismatch", "dense.vector_mapping_missing"],
)
def test_health_reports_disabled_dense_for_mapping_failures(
    monkeypatch,
    warning: str,
) -> None:
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")
    from config import get_settings

    get_settings.cache_clear()
    client = _client_with_status(
        {
            "elasticsearch": "configured",
            "reranker": "noop",
            "neo4j": "configured",
            "llm": "extractive",
            "embedding": "disabled",
            "dense_retrieval": "disabled",
            "runtime": "configured",
        },
        warnings=[warning],
    )

    payload = client.get("/health").json()

    assert payload["status"] == "degraded"
    assert payload["embedding"] == "disabled"
    assert payload["dense_retrieval"] == "disabled"
    assert warning not in payload.values()
    get_settings.cache_clear()
