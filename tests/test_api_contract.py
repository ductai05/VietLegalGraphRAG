from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import create_app


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

def test_health_endpoint_reports_configured_services() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert "elasticsearch" in payload
    assert "neo4j" in payload


# ---------------------------------------------------------------------------
# Search endpoint
# ---------------------------------------------------------------------------

def test_search_endpoint_accepts_mvp_request() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/search",
        json={
            "query": "Dieu kien cap giay phep xay dung la gi?",
            "retrieval_mode": "hybrid",
            "rerank": {"enabled": False},
            "top_k": 2,
            "filters": {"effect_status": "Con hieu luc"},
            "graph": {"enabled": False, "use_lightrag": False, "max_hops": 1},
            "llm": {"temperature": 0.2, "max_context_chunks": 8},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_mode"] == "hybrid"
    assert "results" in payload


def test_search_endpoint_rejects_empty_query() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/search",
        json={
            "query": "",
            "retrieval_mode": "hybrid",
            "rerank": {"enabled": False},
            "top_k": 2,
            "filters": {},
            "graph": {"enabled": False, "use_lightrag": False, "max_hops": 1},
            "llm": {"temperature": 0.2, "max_context_chunks": 8},
        },
    )

    assert response.status_code == 422


def test_search_endpoint_rejects_invalid_retrieval_mode() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/search",
        json={
            "query": "test query",
            "retrieval_mode": "bm25",
            "top_k": 2,
        },
    )

    assert response.status_code == 422


def test_search_endpoint_rejects_candidate_k_less_than_top_k() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/search",
        json={
            "query": "test query",
            "rerank": {"enabled": True, "candidate_k": 3},
            "top_k": 5,
        },
    )

    assert response.status_code == 422


def test_search_endpoint_rejects_invalid_temperature() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/search",
        json={
            "query": "test query",
            "llm": {"temperature": 1.5},
            "top_k": 2,
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Answer endpoint
# ---------------------------------------------------------------------------

def test_answer_endpoint_returns_trace() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/answer",
        json={
            "query": "Van ban nao sua doi quy dinh nay?",
            "retrieval_mode": "hybrid",
            "rerank": {"enabled": True, "candidate_k": 5},
            "top_k": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert payload["retrieval_trace"]["execution_mode"] == "hybrid_rerank"


def test_answer_endpoint_returns_contract_shape() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/answer",
        json={
            "query": "test",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # All required top-level keys must be present
    for key in ("answer", "citations", "retrieval_context", "graph_context", "retrieval_trace"):
        assert key in payload, f"Missing key: {key}"


def test_answer_endpoint_rejects_candidate_k_less_than_top_k() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/answer",
        json={
            "query": "test query",
            "rerank": {"enabled": True, "candidate_k": 3},
            "top_k": 5,
        },
    )

    assert response.status_code == 422


def test_answer_endpoint_rejects_empty_query() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/answer",
        json={
            "query": "",
            "top_k": 2,
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Documents endpoint
# ---------------------------------------------------------------------------

def test_document_graph_endpoint_returns_contract_shape() -> None:
    client = TestClient(create_app())

    response = client.get("/documents/42/graph")

    assert response.status_code == 200
    payload = response.json()
    assert "center" in payload
    assert "nodes" in payload
    assert "edges" in payload
    assert "query_intent" in payload


def test_document_version_chain_endpoint_returns_contract_shape() -> None:
    client = TestClient(create_app())

    response = client.get("/documents/42/version-chain")

    assert response.status_code == 200
    payload = response.json()
    assert "doc_id" in payload
    assert "chain" in payload


# ---------------------------------------------------------------------------
# OpenAPI schema
# ---------------------------------------------------------------------------

def test_openapi_schema_is_generated() -> None:
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["openapi"]  # e.g. "3.1.0"
    assert "paths" in payload
    # Verify all documented paths are present
    paths = payload["paths"]
    assert "/health" in paths
    assert "/search" in paths
    assert "/answer" in paths
    assert "/documents/{doc_id}/graph" in paths
    assert "/documents/{doc_id}/version-chain" in paths


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def test_cors_allows_configured_frontend_origin() -> None:
    client = TestClient(create_app())

    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_unconfigured_origin() -> None:
    client = TestClient(create_app())

    response = client.options(
        "/health",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    # Wildcard must not be present; non-configured origin gets no CORS header
    assert response.headers.get("access-control-allow-origin") != "*"


# ---------------------------------------------------------------------------
# Search result shape (detailed)
# ---------------------------------------------------------------------------

def test_search_result_items_match_retrieval_hit_contract() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/search",
        json={
            "query": "test",
            "retrieval_mode": "hybrid",
            "rerank": {"enabled": False},
            "top_k": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    results = payload["results"]
    assert isinstance(results, list)
    assert len(results) >= 1
    hit = results[0]
    # Must have the keys defined by RetrievalHit contract
    for key in ("rank", "chunk_id", "doc_id", "title", "text", "citation"):
        assert key in hit, f"Missing key in search result: {key}"
