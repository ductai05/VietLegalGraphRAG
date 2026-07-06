from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_chat_frontend_posts_messages_to_backend_answer_api() -> None:
    script = read("src/frontend/app.js")

    assert 'const API_BASE = window.AURORA_API_BASE || "/api";' in script
    assert 'fetch(`${API_BASE}/answer`' in script
    assert '"retrieval_mode": "hybrid"' in script
    assert '"include_trace": true' in script
    assert "payload.retrieval_trace" in script
    assert "payload.citations" in script
    assert "const replies =" not in script
