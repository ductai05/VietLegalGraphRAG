from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

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

# Client-visible warning codes must be short dotted identifiers, never
# exception class names, messages, hosts, or paths.
WARNING_CODE_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def _make_client(monkeypatch, env: dict[str, str] | None = None) -> TestClient:
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
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
    from config import get_settings
    from dependencies import get_runtime_services
    from main import create_app

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    return TestClient(create_app())


def test_runtime_warnings_are_sanitized_codes(monkeypatch) -> None:
    _make_client(
        monkeypatch,
        env={"ELASTICSEARCH_URL": "http://127.0.0.1:59999"},
    )
    from dependencies import get_runtime_services

    runtime = get_runtime_services()
    for warning in runtime.warnings:
        assert WARNING_CODE_PATTERN.match(warning), warning
        assert ":" not in warning
        assert "Error" not in warning and "Exception" not in warning


def test_search_response_warnings_leak_no_exception_details(monkeypatch) -> None:
    client = _make_client(
        monkeypatch,
        env={"ELASTICSEARCH_URL": "http://127.0.0.1:59999"},
    )
    response = client.post("/search", json={"query": "hop dong"})
    assert response.status_code == 200
    for warning in response.json().get("warnings", []):
        assert WARNING_CODE_PATTERN.match(warning), warning


def test_answer_response_warnings_leak_no_exception_details(monkeypatch) -> None:
    client = _make_client(
        monkeypatch,
        env={"ELASTICSEARCH_URL": "http://127.0.0.1:59999"},
    )
    response = client.post("/answer", json={"query": "hop dong"})
    assert response.status_code == 200
    for warning in response.json().get("warnings", []):
        assert WARNING_CODE_PATTERN.match(warning), warning


def test_warnings_never_contain_secrets_or_hosts(monkeypatch) -> None:
    secret = "super-secret-value-12345"
    client = _make_client(
        monkeypatch,
        env={
            "ELASTICSEARCH_URL": "http://127.0.0.1:59999",
            "ELASTICSEARCH_API_KEY": secret,
            "NEO4J_PASSWORD": secret,
        },
    )
    response = client.post("/search", json={"query": "hop dong"})
    body = response.text
    assert secret not in body
    assert "59999" not in body
