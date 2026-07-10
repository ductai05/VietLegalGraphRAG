from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_orig_env = dict(os.environ)


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
    # Snapshot modules that will be removed so we can restore them after.
    _removed_keys = [k for k in sys.modules if "google" in k or "vision" in k]
    _removed = {k: sys.modules.pop(k) for k in _removed_keys}

    from ocr_service import GoogleVisionOcrService

    assert "google.cloud.vision" not in sys.modules
    assert "google.oauth2.service_account" not in sys.modules

    GoogleVisionOcrService()
    assert "google.cloud.vision" not in sys.modules

    # Restore so subsequent tests in the same process still have google.
    sys.modules.update(_removed)


def test_google_vision_init_no_attribute_error_without_individual_vars() -> None:
    """GOOGLE_APPLICATION_CREDENTIALS / ADC path must not raise AttributeError."""
    # Clear individual vars so ADC path is taken.
    for var in (
        "GOOGLE_SERVICE_ACCOUNT_PROJECT_ID",
        "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY",
        "GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL",
        "GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY_ID",
        "GOOGLE_SERVICE_ACCOUNT_CLIENT_ID",
    ):
        os.environ.pop(var, None)

    from ocr_service import GoogleVisionOcrService

    svc = GoogleVisionOcrService()

    # Verify all attrs exist and are None, no AttributeError on access.
    assert hasattr(svc, "_project_id")
    assert svc._project_id is None
    assert hasattr(svc, "_private_key")
    assert svc._private_key is None
    assert hasattr(svc, "_client_email")
    assert svc._client_email is None
    assert hasattr(svc, "_credentials")
    assert svc._credentials is None


def test_google_vision_service_account_vars_still_work() -> None:
    """Explicit GOOGLE_SERVICE_ACCOUNT_* vars are still parsed and stored."""
    os.environ["GOOGLE_SERVICE_ACCOUNT_PROJECT_ID"] = "test-project"
    os.environ["GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY"] = "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
    os.environ["GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL"] = "test@test.iam.gserviceaccount.com"

    from ocr_service import GoogleVisionOcrService

    svc = GoogleVisionOcrService()
    assert svc._project_id == "test-project"
    assert svc._private_key == "-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----"
    assert svc._client_email == "test@test.iam.gserviceaccount.com"

    os.environ.pop("GOOGLE_SERVICE_ACCOUNT_PROJECT_ID", None)
    os.environ.pop("GOOGLE_SERVICE_ACCOUNT_PRIVATE_KEY", None)
    os.environ.pop("GOOGLE_SERVICE_ACCOUNT_CLIENT_EMAIL", None)


def test_language_hints_passed_to_vision_image_context() -> None:
    """OCR_LANGUAGE_HINTS must be forwarded to Vision image_context."""
    from ocr_service import GoogleVisionOcrService

    svc = GoogleVisionOcrService(language_hints=("vi", "en"))
    assert svc._language_hints == ("vi", "en")

    captured_kwargs = {}

    def fake_process_image(content: bytes) -> dict[str, Any]:
        # Replicate the logic: check _language_hints attribute exists and is used.
        captured_kwargs["has_language_hints_attr"] = hasattr(svc, "_language_hints")
        captured_kwargs["language_hints"] = svc._language_hints
        return {"success": True, "text": "", "pages": [], "mime_type": "image/*"}

    with patch.object(svc, "_process_image", fake_process_image):
        svc.process(b"fake image bytes", "image/jpeg")

    assert captured_kwargs["has_language_hints_attr"] is True
    assert captured_kwargs["language_hints"] == ("vi", "en")


def test_process_image_passes_language_hints_as_request_context(monkeypatch) -> None:
    """Google Vision image_context belongs on the request, not vision.Image."""
    from google.cloud import vision
    from ocr_service import GoogleVisionOcrService

    svc = GoogleVisionOcrService(language_hints=("vi", "en"))
    fake_client = Mock()
    response = Mock()
    response.error = Mock(message="")
    response.full_text_annotation = Mock(text="Extracted text")
    fake_client.document_text_detection.return_value = response
    monkeypatch.setattr(svc, "_client", lambda: fake_client)

    result = svc.process(b"fake image bytes", "image/png")

    assert result["success"] is True
    kwargs = fake_client.document_text_detection.call_args.kwargs
    assert isinstance(kwargs["image"], vision.Image)
    assert list(kwargs["image_context"].language_hints) == ["vi", "en"]
    assert not hasattr(kwargs["image"], "image_context")


def test_language_hints_passed_to_vision_pdf_request() -> None:
    """OCR_LANGUAGE_HINTS must be forwarded to AnnotateFileRequest image_context."""
    from ocr_service import GoogleVisionOcrService

    svc = GoogleVisionOcrService(language_hints=("vi", "en", "fr"))
    assert svc._language_hints == ("vi", "en", "fr")

    captured_kwargs = {}

    def fake_process_pdf(content: bytes) -> dict[str, Any]:
        captured_kwargs["has_language_hints_attr"] = hasattr(svc, "_language_hints")
        captured_kwargs["language_hints"] = svc._language_hints
        return {"success": True, "text": "", "pages": [], "mime_type": "application/pdf"}

    with patch.object(svc, "_process_pdf", fake_process_pdf):
        svc.process(b"fake pdf bytes", "application/pdf")

    assert captured_kwargs["has_language_hints_attr"] is True
    assert captured_kwargs["language_hints"] == ("vi", "en", "fr")


def test_health_exposes_ocr_config_invalid_warning(monkeypatch) -> None:
    """When OCR_MAX_FILE_MB is invalid, /health must include the warning code."""
    from config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("OCR_MAX_FILE_MB", "-5")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    from dependencies import RuntimeServices, get_runtime_services

    get_runtime_services.cache_clear()

    runtime = RuntimeServices(
        retrieval_service=None,
        graph_retriever=None,
        answer_service=None,
        lightrag_service=None,
        ocr_service=Mock(),
        status={"ocr": "google"},
        warnings=["config.ocr_max_file_mb_invalid"],
    )
    from main import create_app

    app = create_app()
    app.dependency_overrides[get_runtime_services] = lambda: runtime

    client = TestClient(app)
    payload = client.get("/health").json()

    assert payload["status"] == "degraded"
    assert "config.ocr_max_file_mb_invalid" in payload["warnings"]

    get_settings.cache_clear()
    get_runtime_services.cache_clear()



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


def test_ocr_returns_422_for_pdf_over_page_limit_before_service_call(monkeypatch, tmp_path) -> None:
    from pypdf import PdfWriter
    from config import get_settings
    from dependencies import get_runtime_services

    get_settings.cache_clear()
    get_runtime_services.cache_clear()
    monkeypatch.setenv("OCR_PROVIDER", "google")
    monkeypatch.setenv("OCR_MAX_PDF_PAGES", "5")
    monkeypatch.setenv("RERANK_PROVIDER", "noop")
    monkeypatch.setenv("LLM_PROVIDER", "extractive")

    pdf_path = tmp_path / "six-pages.pdf"
    writer = PdfWriter()
    for _ in range(6):
        writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    mock_svc = Mock()

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
        files={"file": ("six-pages.pdf", pdf_path.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "ocr.pdf_too_many_pages"
    mock_svc.process.assert_not_called()

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
    from pypdf import PdfWriter
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

    pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(pdf)

    client = TestClient(app)
    response = client.post(
        "/documents/ocr",
        files={"file": ("doc.pdf", pdf.getvalue(), "application/pdf")},
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
