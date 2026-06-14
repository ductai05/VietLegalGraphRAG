from __future__ import annotations

import os
from pathlib import Path

import pytest

from contract_ocr.config import Settings
from contract_ocr.service import ContractReviewService


RUN_INTEGRATION = os.getenv("RUN_OCR_INTEGRATION") == "1"


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="Set RUN_OCR_INTEGRATION=1 to run cached PP-OCRv6 inference.",
)
def test_real_ppocrv6_detector_and_vietnamese_recognizer() -> None:
    pdf_path = Path(__file__).resolve().parents[2] / "docs" / "outline.pdf"
    assert pdf_path.is_file()
    service = ContractReviewService(
        Settings(
            ocr_device="auto",
            max_pages=1,
            default_pdf_dpi=120,
            text_rec_score_threshold=0.35,
        )
    )

    document = service.ocr_pdf(
        pdf_path,
        requested_pages=1,
        dpi=120,
        score_threshold=0.35,
    )

    assert document.processed_pages == 1
    assert document.line_count >= 5
    assert document.average_confidence > 0.5
    assert document.detector_model == "PP-OCRv6_medium_det"
    assert document.recognizer_model == "EasyOCR (vi,en)"
    assert document.device in {"cpu", "gpu:0"}
