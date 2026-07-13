from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_chat_frontend_posts_messages_to_backend_answer_api() -> None:
    script = read("src/frontend/app.js")

    assert "function resolveApiBase" in script
    assert "http://localhost:8000" in script
    assert 'fetchWithTimeout(`${API_BASE}/answer`' in script
    assert '"retrieval_mode": "hybrid"' in script
    assert '"include_trace": true' in script
    assert "payload.retrieval_trace" in script
    assert "payload.citations" in script
    assert "const replies =" not in script


def test_chat_frontend_uses_timeout_and_distinct_timeout_copy() -> None:
    script = read("src/frontend/app.js")

    assert "AbortController" in script
    assert "REQUEST_TIMEOUT_MS = 30000" in script
    assert "request.timeout" in script
    assert "The API request timed out" in script


def test_handoff_copy_is_explicitly_demo_only() -> None:
    script = read("src/frontend/app.js")

    assert "demo only" in script.lower()
    assert "Someone will pick up the full conversation history" not in script


def test_chat_frontend_has_ocr_upload_control_and_safe_rendering() -> None:
    chat_html = read("src/frontend/chat.html")
    script = read("src/frontend/app.js")

    assert 'id="ocr-form"' in chat_html
    assert 'id="ocr-file"' in chat_html
    assert 'fetchWithTimeout(`${API_BASE}/documents/ocr`' in script
    assert "FormData" in script
    assert "renderOcrPreview" in script
    assert ".textContent" in script
    assert "innerHTML = payload.text" not in script


def test_pages_define_api_base_before_app_script() -> None:
    for path in ("src/frontend/index.html", "src/frontend/chat.html"):
        html = read(path)
        assert "window.AURORA_API_BASE" in html
        assert html.index("window.AURORA_API_BASE") < html.index('src="app.js"')
