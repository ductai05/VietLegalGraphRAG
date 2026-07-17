from __future__ import annotations

import json
import sys
import importlib
from pathlib import Path

import pytest
pytest.skip("FastAPI backend is obsolete/removed in this branch", allow_module_level=True)
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


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    _reload_backend_modules()
    from config import get_settings
    from dependencies import get_runtime_services
    from main import create_app

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    return TestClient(create_app())


def test_answer_non_streaming_by_default(client: TestClient) -> None:
    response = client.post("/answer", json={"query": "hop dong", "top_k": 2})
    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert "citations" in payload
    assert "retrieval_trace" in payload
    assert not isinstance(payload.get("answer"), list)


def test_answer_streaming_response(client: TestClient) -> None:
    response = client.post(
        "/answer",
        json={"query": "hop dong", "top_k": 2, "stream": True},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    # Parse SSE stream
    chunks = []
    for line in response.iter_lines():
        if not line:
            continue
        line_str = line if isinstance(line, str) else line.decode("utf-8")
        if line_str.startswith("data: "):
            chunk_data = json.loads(line_str[6:])
            chunks.append(chunk_data)

    assert len(chunks) >= 2
    # First chunk should be metadata
    assert chunks[0]["type"] == "metadata"
    assert "citations" in chunks[0]
    assert "retrieval_trace" in chunks[0]

    # Last chunk should be done
    assert chunks[-1]["type"] == "done"
    assert "retrieval_trace" in chunks[-1]

    # Intermediate chunks (if any) should be token chunks
    for chunk in chunks[1:-1]:
        assert chunk["type"] == "token"
        assert "text" in chunk
