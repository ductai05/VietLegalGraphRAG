from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_chat_frontend_posts_messages_to_backend_answer_api() -> None:
    api_js = read("src/frontend/src/lib/api.js")
    chat_jsx = read("src/frontend/src/pages/Chat.jsx")

    assert "resolveApiBase" in api_js
    assert "http://localhost:8000" in api_js
    assert 'fetchWithTimeout(`${API_BASE}/answer`' in api_js
    assert '"retrieval_mode": "hybrid"' in api_js
    assert '"include_trace": true' in api_js
    assert "payload.retrieval_trace" in chat_jsx
    assert "payload.citations" in chat_jsx
    assert "const replies =" not in chat_jsx


def test_chat_frontend_uses_timeout_and_distinct_timeout_copy() -> None:
    api_js = read("src/frontend/src/lib/api.js")
    chat_jsx = read("src/frontend/src/pages/Chat.jsx")

    assert "AbortController" in api_js
    assert "REQUEST_TIMEOUT_MS = 30000" in api_js
    assert "request.timeout" in api_js
    assert "Yêu cầu đã hết thời gian chờ" in chat_jsx


def test_handoff_copy_is_explicitly_demo_only() -> None:
    chat_jsx = read("src/frontend/src/pages/Chat.jsx")

    assert "demo" in chat_jsx.lower()
    assert "Someone will pick up the full conversation history" not in chat_jsx


def test_chat_frontend_has_ocr_upload_control_and_safe_rendering() -> None:
    ocr_form = read("src/frontend/src/components/chat/OcrForm.jsx")
    api_js = read("src/frontend/src/lib/api.js")
    message_jsx = read("src/frontend/src/components/chat/Message.jsx")

    assert 'id="ocr-form"' in ocr_form
    assert 'id="ocr-file"' in ocr_form
    assert 'fetchWithTimeout(`${API_BASE}/documents/ocr`' in api_js
    assert "FormData" in api_js
    assert "ocr-preview" in message_jsx
    assert "renderOcrPreview" in message_jsx
    assert "innerHTML =" not in message_jsx


def test_pages_define_api_base_before_app_script() -> None:
    html = read("src/frontend/index.html")
    assert "window.AURORA_API_BASE" in html
    assert html.index("window.AURORA_API_BASE") < html.index('src="/src/main.jsx"')
