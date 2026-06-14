from __future__ import annotations

from pathlib import Path

from contract_ocr.config import Settings
from contract_ocr.models import OCRLine, OCRPage
from contract_ocr.service import ContractReviewService


class FakeOCREngine:
    device = "cpu"

    def __init__(self) -> None:
        self.calls = []

    def recognize_page(self, image, page_number, score_threshold):
        self.calls.append((image.shape, page_number, score_threshold))
        return OCRPage(
            page_number=page_number,
            width=image.shape[1],
            height=image.shape[0],
            lines=[OCRLine(f"Nội dung trang {page_number}", 0.95)],
        )


def test_service_ocr_emits_progress_and_document_to_consumers(
    sample_pdf: Path,
) -> None:
    engine = FakeOCREngine()
    consumed = []
    progress = []

    class FakeConsumer:
        def consume(self, document):
            consumed.append(document)

    service = ContractReviewService(
        Settings(max_pages=5),
        ocr_engine=engine,
        document_consumers=[FakeConsumer()],
    )

    result = service.ocr_pdf(
        sample_pdf,
        requested_pages=1,
        dpi=96,
        score_threshold=0.5,
        progress_callback=lambda *args: progress.append(args),
    )

    assert result.filename == "contract.pdf"
    assert result.total_pages == 2
    assert result.processed_pages == 1
    assert result.truncated is True
    assert result.device == "cpu"
    assert result.elapsed_seconds >= 0
    assert result.text.endswith("Nội dung trang 1")
    assert consumed == [result]
    assert len(engine.calls) == 1
    assert engine.calls[0][1:] == (1, 0.5)
    assert progress == [(1, 1, "Đang OCR trang 1/1")]


def test_service_clamps_requested_pages_to_at_least_one_and_maximum(
    sample_pdf: Path,
) -> None:
    engine = FakeOCREngine()
    service = ContractReviewService(
        Settings(max_pages=1),
        ocr_engine=engine,
    )

    result = service.ocr_pdf(
        sample_pdf,
        requested_pages=0,
        dpi=96,
        score_threshold=0.4,
    )

    assert result.processed_pages == 1
    assert len(engine.calls) == 1


def test_service_delegates_contract_analysis() -> None:
    calls = []

    class FakeAnalyzer:
        def analyze(self, **kwargs):
            calls.append(kwargs)
            return "analysis"

    callback = lambda *args: None
    service = ContractReviewService(
        Settings(),
        ocr_engine=FakeOCREngine(),
        analyzer=FakeAnalyzer(),
    )

    result = service.analyze_contract(
        contract_text="text",
        api_key="key",
        model="model",
        progress_callback=callback,
    )

    assert result == "analysis"
    assert calls == [
        {
            "contract_text": "text",
            "api_key": "key",
            "model": "model",
            "progress_callback": callback,
        }
    ]
