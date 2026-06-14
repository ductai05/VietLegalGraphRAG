from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from contract_ocr.config import Settings
from contract_ocr.exceptions import ContractAppError
from contract_ocr.models import OCRDocument, OCRLine, OCRPage
from ui import _status_markdown, _uploaded_path, build_app


class RecordingProgress:
    def __init__(self) -> None:
        self.calls = []

    def __call__(self, value, desc=None) -> None:
        self.calls.append((value, desc))


def _document(truncated: bool = False) -> OCRDocument:
    return OCRDocument(
        filename="contract.pdf",
        total_pages=2 if truncated else 1,
        processed_pages=1,
        truncated=truncated,
        detector_model="det",
        recognizer_model="rec",
        device="gpu:0",
        elapsed_seconds=1.25,
        pages=[
            OCRPage(
                page_number=1,
                width=100,
                height=200,
                lines=[OCRLine("Điều khoản", 0.9)],
            )
        ],
    )


def _callbacks(app):
    return {dependency.fn.__name__: dependency.fn for dependency in app.fns.values()}


def test_uploaded_path_supports_paths_and_file_objects(tmp_path: Path) -> None:
    path = tmp_path / "contract.pdf"

    assert _uploaded_path(str(path)) == str(path)
    assert _uploaded_path(path) == str(path)
    assert _uploaded_path(SimpleNamespace(name=str(path))) == str(path)

    with pytest.raises(ContractAppError, match="tải lên"):
        _uploaded_path(None)
    with pytest.raises(ContractAppError, match="đường dẫn"):
        _uploaded_path(object())


def test_status_markdown_contains_metrics_and_truncation() -> None:
    status = _status_markdown(_document(truncated=True))

    assert "gpu:0" in status
    assert "90.0%" in status
    assert "1.25 giây" in status
    assert "1/2 trang" in status


def test_build_app_registers_expected_callbacks() -> None:
    app = build_app(Settings(max_pages=3), service=SimpleNamespace())

    assert set(_callbacks(app)) == {
        "run_ocr",
        "run_analysis",
        "run_all",
        "clear_all",
    }


def test_run_ocr_success_updates_outputs_and_progress() -> None:
    document = _document()
    calls = []

    class FakeService:
        def ocr_pdf(self, **kwargs):
            calls.append(kwargs)
            kwargs["progress_callback"](1, 1, "OCR")
            return document

    app = build_app(Settings(max_pages=3), service=FakeService())
    run_ocr = _callbacks(app)["run_ocr"]
    progress = RecordingProgress()

    outputs = run_ocr("contract.pdf", 2, 180, 0.45, progress)

    assert "OCR hoàn tất" in outputs[0]
    assert outputs[1] == document.text
    assert outputs[2]["filename"] == "contract.pdf"
    assert outputs[3] == document.table_rows()
    assert outputs[4] == document.to_dict()
    assert calls[0]["pdf_path"] == "contract.pdf"
    assert calls[0]["requested_pages"] == 2
    assert progress.calls == [(1.0, "OCR")]


@pytest.mark.parametrize(
    ("exception", "expected_heading"),
    [
        (ContractAppError("bad pdf"), "Không thể OCR"),
        (RuntimeError("boom"), "Lỗi không mong đợi khi OCR"),
    ],
)
def test_run_ocr_formats_known_and_unexpected_errors(
    exception: Exception,
    expected_heading: str,
) -> None:
    class FailingService:
        def ocr_pdf(self, **kwargs):
            raise exception

    app = build_app(Settings(), service=FailingService())
    run_ocr = _callbacks(app)["run_ocr"]

    outputs = run_ocr("contract.pdf", 1, 96, 0.5, RecordingProgress())

    assert expected_heading in outputs[0]
    assert outputs[1:] == ("", {}, [], None)


def test_run_analysis_success_and_error_paths() -> None:
    class FakeService:
        def __init__(self) -> None:
            self.error = None

        def analyze_contract(self, **kwargs):
            if self.error:
                raise self.error
            kwargs["progress_callback"](1, 2, "Gemini")
            return "analysis"

    service = FakeService()
    app = build_app(Settings(), service=service)
    run_analysis = _callbacks(app)["run_analysis"]
    progress = RecordingProgress()

    assert run_analysis("text", "key", "model", progress) == "analysis"
    assert progress.calls == [(0.5, "Gemini")]

    service.error = ContractAppError("invalid key")
    assert "Không thể phân tích" in run_analysis(
        "text", "key", "model", RecordingProgress()
    )

    service.error = RuntimeError("boom")
    assert "Lỗi không mong đợi khi gọi Gemini" in run_analysis(
        "text", "key", "model", RecordingProgress()
    )


def test_run_all_success_and_clear_outputs() -> None:
    document = _document()

    class FakeService:
        def ocr_pdf(self, **kwargs):
            return document

        def analyze_contract(self, **kwargs):
            kwargs["progress_callback"](1, 1, "Gemini")
            return "analysis"

    app = build_app(Settings(), service=FakeService())
    callbacks = _callbacks(app)
    progress = RecordingProgress()

    outputs = callbacks["run_all"](
        "contract.pdf",
        "key",
        "model",
        1,
        96,
        0.5,
        progress,
    )

    assert outputs[1] == document.text
    assert outputs[5] == "analysis"
    assert progress.calls == [(1.0, "Gemini")]
    assert callbacks["clear_all"]() == (None, "", "", {}, [], None, "")


@pytest.mark.parametrize(
    ("exception", "expected_heading"),
    [
        (ContractAppError("bad request"), "Không thể hoàn tất"),
        (RuntimeError("boom"), "Lỗi không mong đợi"),
    ],
)
def test_run_all_formats_errors(
    exception: Exception,
    expected_heading: str,
) -> None:
    class FailingService:
        def ocr_pdf(self, **kwargs):
            raise exception

    app = build_app(Settings(), service=FailingService())
    run_all = _callbacks(app)["run_all"]

    outputs = run_all(
        "contract.pdf",
        "key",
        "model",
        1,
        96,
        0.5,
        RecordingProgress(),
    )

    assert expected_heading in outputs[0]
    assert outputs[1:] == ("", {}, [], None, "")
