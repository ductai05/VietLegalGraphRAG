from __future__ import annotations

import importlib
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

RUNTIME_ENV_KEYS = [
    "ELASTICSEARCH_URL",
    "ELASTICSEARCH_API_KEY",
    "ELASTICSEARCH_USERNAME",
    "ELASTICSEARCH_PASSWORD",
    "RERANK_PROVIDER",
    "RERANK_MODEL_ALLOWLIST",
    "VOYAGE_API_KEY",
    "LLM_PROVIDER",
    "LLM_API_KEY",
    "NEO4J_PASSWORD",
]


def _reload_backend_modules() -> None:
    # Order matters: routes must rebind the reloaded dependencies module and
    # main must rebind the reloaded routers.
    for name in [
        "config",
        "dependencies",
        "routes.health",
        "routes.search",
        "routes.documents",
        "main",
    ]:
        if name in sys.modules:
            importlib.reload(sys.modules[name])


def _make_client(monkeypatch) -> TestClient:
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    _reload_backend_modules()
    from config import get_settings
    from dependencies import get_runtime_services
    from main import create_app

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    return TestClient(create_app())


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    return _make_client(monkeypatch)


# --- Unit tests: dataclass bounds (retrieval_modes) ---


def test_retrieval_request_rejects_top_k_over_bound() -> None:
    from retrieval_modes import RetrievalRequest

    with pytest.raises(ValueError, match="top_k"):
        RetrievalRequest(query="q", top_k=51, rerank={"enabled": False})


def test_rerank_config_rejects_candidate_k_over_bound() -> None:
    from retrieval_modes import RerankConfig

    with pytest.raises(ValueError, match="candidate_k"):
        RerankConfig(candidate_k=201)


def test_rerank_config_rejects_timeout_over_bound() -> None:
    from retrieval_modes import RerankConfig

    with pytest.raises(ValueError, match="timeout_ms"):
        RerankConfig(timeout_ms=120001)


def test_rerank_config_rejects_batch_size_over_bound() -> None:
    from retrieval_modes import RerankConfig

    with pytest.raises(ValueError, match="batch_size"):
        RerankConfig(batch_size=65)


def test_graph_config_rejects_max_hops_over_bound() -> None:
    from retrieval_modes import GraphConfig

    with pytest.raises(ValueError, match="max_hops"):
        GraphConfig(max_hops=3)


def test_llm_config_rejects_max_context_chunks_over_bound() -> None:
    from retrieval_modes import LLMConfig

    with pytest.raises(ValueError, match="max_context_chunks"):
        LLMConfig(max_context_chunks=33)


def test_rerank_default_model_aligned_between_schema_and_dataclass() -> None:
    from retrieval_modes import RerankConfig
    from schemas import RerankConfigModel

    assert RerankConfig().model == "rerank-2.5"
    assert RerankConfigModel().model == RerankConfig().model


def test_dataclass_lower_bounds_still_enforced() -> None:
    from retrieval_modes import RerankConfig, RetrievalRequest

    with pytest.raises(ValueError):
        RetrievalRequest(query="q", top_k=0, rerank={"enabled": False})
    with pytest.raises(ValueError):
        RerankConfig(candidate_k=0)


# --- API tests: invalid /search and /answer requests -> 4xx ---


def test_search_rejects_top_k_over_bound(client: TestClient) -> None:
    response = client.post("/search", json={"query": "hop dong", "top_k": 1000})
    assert response.status_code == 422


def test_search_rejects_candidate_k_over_bound(client: TestClient) -> None:
    response = client.post(
        "/search",
        json={"query": "hop dong", "rerank": {"candidate_k": 500}},
    )
    assert response.status_code == 422


def test_answer_rejects_candidate_k_below_top_k(client: TestClient) -> None:
    response = client.post(
        "/answer",
        json={"query": "hop dong", "top_k": 10, "rerank": {"candidate_k": 5}},
    )
    assert response.status_code == 422


def test_answer_rejects_max_hops_over_bound(client: TestClient) -> None:
    response = client.post(
        "/answer",
        json={"query": "hop dong", "graph": {"max_hops": 5}},
    )
    assert response.status_code == 422


def test_search_rejects_empty_query(client: TestClient) -> None:
    response = client.post("/search", json={"query": ""})
    assert response.status_code == 422


def test_search_rejects_non_allowlisted_rerank_model(client: TestClient) -> None:
    response = client.post(
        "/search",
        json={"query": "hop dong", "rerank": {"model": "attacker-model"}},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "validation_error"
    assert "rerank-2.5" in detail["allowed"]


def test_answer_rejects_non_allowlisted_rerank_model(client: TestClient) -> None:
    response = client.post(
        "/answer",
        json={"query": "hop dong", "rerank": {"model": "attacker-model"}},
    )
    assert response.status_code == 422


def test_disabled_rerank_skips_model_allowlist(client: TestClient) -> None:
    response = client.post(
        "/search",
        json={
            "query": "hop dong",
            "rerank": {"enabled": False, "model": "anything-goes"},
        },
    )
    assert response.status_code == 200


def test_allowlisted_rerank_model_accepted(client: TestClient) -> None:
    response = client.post(
        "/search",
        json={"query": "hop dong", "rerank": {"model": "rerank-2.5-lite"}},
    )
    assert response.status_code == 200


def test_wildcard_allowlist_accepts_any_model(monkeypatch) -> None:
    monkeypatch.setenv("RERANK_MODEL_ALLOWLIST", "*")
    client = _make_client(monkeypatch)
    monkeypatch.setenv("RERANK_MODEL_ALLOWLIST", "*")
    from config import get_settings

    get_settings.cache_clear()
    response = client.post(
        "/search",
        json={"query": "hop dong", "rerank": {"model": "any-model"}},
    )
    assert response.status_code == 200


def test_valid_request_still_succeeds_in_fallback_mode(client: TestClient) -> None:
    response = client.post("/answer", json={"query": "hop dong", "top_k": 2})
    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"]
    assert "retrieval_trace" in payload
