from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _client_with_ocr(
    ocr_service: object,
    ocr_status: str = "disabled",
    warnings: list[str] | None = None,
) -> TestClient:
    from dependencies import RuntimeServices, get_runtime_services
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=ocr_service,
        status={"ocr": ocr_status},
        warnings=warnings or [],
    )
    app = create_app()
    app.dependency_overrides[get_runtime_services] = lambda: runtime
    return TestClient(app)


# =============================================================================
# Service-level: OcrService protocol / NoopOcrService
# =============================================================================

def test_noop_service_returns_empty_result() -> None:
    from ocr_service import NoopOcrService

    svc = NoopOcrService()
    result = svc.process(b"fake bytes", "image/jpeg")

    assert result["success"] is False
    assert result["text"] == ""
    assert result["pages"] == []


# =============================================================================
# GoogleVisionOcrService: lazy import
# =============================================================================

def test_vision_import_is_lazy() -> None:
    """google.cloud.vision must not be imported at module level."""
    # Remove any cached imports
    for key in list(sys.modules.keys()):
        if "google" in key or "vision" in key:
            sys.modules.pop(key, None)

    # Import the module
    from ocr_service import GoogleVisionOcrService

    assert "google.cloud.vision" not in sys.modules
    assert "google.oauth2.service_account" not in sys.modules

    # Instantiating should not trigger google import either (init reads env vars only)
    svc = GoogleVisionOcrService()
    assert "google.cloud.vision" not in sys.modules


# =============================================================================
# Route: disabled OCR provider
# =============================================================================

def test_ocr_returns_422_when_disabled(monkeypatch) -> None:
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "none")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    from ocr_service import NoopOcrService
    from dependencies import get_runtime_services

    get_runtime_services.cache_clear()
    get_settings.cache_clear()

    # Force a fresh runtime with disabled OCR
    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=NoopOcrService(),
        status={"ocr": "disabled"},
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("test.jpg", b"fake image", "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "ocr.disabled"

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


# =============================================================================
# Route: empty file
# =============================================================================

def test_ocr_returns_422_on_empty_file(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    mock_svc = Mock()
    mock_svc.process.return_value = {"success": False, "text": "", "pages": []}

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=mock_svc,
        status={"ocr": "google"},
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "ocr.empty_file"

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


# =============================================================================
# Route: oversized file
# =============================================================================

def test_ocr_returns_413_on_oversized_file(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("OCR_MAX_FILE_MB", "1")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    mock_svc = Mock()
    mock_svc.process.return_value = {"success": False, "text": "", "pages": []}

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=mock_svc,
        status={"ocr": "google"},
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    # File larger than 1MB
    large_content = b"x" * (2 * 1024 * 1024)
    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("large.jpg", large_content, "image/jpeg")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "ocr.file_too_large"

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


# =============================================================================
# Route: unsupported MIME type
# =============================================================================

def test_ocr_returns_415_on_unsupported_mime(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("OCR_ALLOWED_MIME_TYPES", "image/jpeg,image/png")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    mock_svc = Mock()
    mock_svc.process.return_value = {"success": False, "text": "", "pages": []}

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=mock_svc,
        status={"ocr": "google"},
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("doc.docx", b"PK...", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "ocr.unsupported_media_type"

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


# =============================================================================
# Route: successful OCR result
# =============================================================================

def test_ocr_returns_200_with_valid_result(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    mock_svc = Mock()
    mock_svc.process.return_value = {
        "success": True,
        "text": "Extracted text",
        "pages": [{"page_num": 1, "text": "Extracted text"}],
    }

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=mock_svc,
        status={"ocr": "google"},
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("scan.jpg", b"fake image bytes", "image/jpeg")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["text"] == "Extracted text"
    assert len(data["pages"]) == 1
    assert data["provider"] == "google"
    assert data["warnings"] == []

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


def test_ocr_warns_when_no_text_extracted(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    mock_svc = Mock()
    mock_svc.process.return_value = {
        "success": False,
        "text": "",
        "pages": [],
    }

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=mock_svc,
        status={"ocr": "google"},
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("blank.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "ocr.no_text_extracted" in data["warnings"]

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


# =============================================================================
# Route: provider error -> 502
# =============================================================================

def test_ocr_returns_502_on_provider_error(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    mock_svc = Mock()
    mock_svc.process.side_effect = RuntimeError("boom")

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=mock_svc,
        status={"ocr": "google"},
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("scan.jpg", b"image bytes", "image/jpeg")},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "ocr.provider_error"

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


# =============================================================================
# Route: ValueError (bad MIME) -> 415
# =============================================================================

def test_ocr_returns_415_on_value_error_from_service(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    mock_svc = Mock()
    mock_svc.process.side_effect = ValueError("Unsupported mime type: text/csv")

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=mock_svc,
        status={"ocr": "google"},
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )

    assert response.status_code == 415
    assert "Unsupported mime type" in response.json()["detail"]

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


# =============================================================================
# Health: OCR status key present
# =============================================================================

def test_health_includes_ocr_key(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=Mock(),
        status={
            "ocr": "google",
            "elasticsearch": "configured",
            "neo4j": "configured",
            "llm": "extractive",
            "reranker": "noop",
            "runtime": "configured",
        },
        warnings=[],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    payload = client.get("/health").json()

    assert "ocr" in payload
    assert payload["ocr"] == "google"

    get_settings.cache_clear()
    get_runtime_services.cache_clear()


def test_health_degraded_when_configured_ocr_falls_to_disabled(monkeypatch) -> None:
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    from dependencies import RuntimeServices
    from main import create_app

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=Mock(),
        status={
            "ocr": "disabled",
            "elasticsearch": "configured",
            "neo4j": "configured",
            "llm": "extractive",
            "reranker": "noop",
            "runtime": "configured",
        },
        warnings=["ocr.init_failed"],
    )
    app = create_app()
    from dependencies import get_runtime_services as _get_runtime
    app.dependency_overrides[_get_runtime] = lambda: runtime

    client = TestClient(app)
    payload = client.get("/health").json()

    assert payload["status"] == "degraded"
    assert payload["ocr"] == "disabled"

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
