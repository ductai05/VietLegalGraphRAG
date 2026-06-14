from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .config import Settings
from .gemini import GeminiContractAnalyzer
from .models import OCRDocument
from .ocr import PaddleOCREngine
from .pdf import PDFRenderer
from .ports import ContractAnalyzer, DocumentConsumer


OCRProgressCallback = Callable[[int, int, str], None]


class ContractReviewService:
    def __init__(
        self,
        settings: Settings,
        ocr_engine: PaddleOCREngine | None = None,
        analyzer: ContractAnalyzer | None = None,
        document_consumers: Sequence[DocumentConsumer] = (),
    ) -> None:
        self.settings = settings
        self.renderer = PDFRenderer(
            max_upload_mb=settings.max_upload_mb,
            max_pages=settings.max_pages,
            max_dpi=settings.max_pdf_dpi,
        )
        self.ocr_engine = ocr_engine or PaddleOCREngine(settings)
        self.analyzer = analyzer or GeminiContractAnalyzer(settings)
        self.document_consumers = tuple(document_consumers)

    def ocr_pdf(
        self,
        pdf_path: str | Path,
        requested_pages: int,
        dpi: int,
        score_threshold: float,
        progress_callback: OCRProgressCallback | None = None,
    ) -> OCRDocument:
        path, total_pages = self.renderer.inspect(pdf_path)
        processed_pages = min(
            total_pages,
            max(1, int(requested_pages)),
            self.settings.max_pages,
        )
        started_at = time.perf_counter()
        pages = []

        for page in self.renderer.iter_pages(
            path,
            dpi=dpi,
            requested_pages=processed_pages,
        ):
            if progress_callback:
                progress_callback(
                    page.page_number,
                    processed_pages,
                    f"Đang OCR trang {page.page_number}/{processed_pages}",
                )
            pages.append(
                self.ocr_engine.recognize_page(
                    page.image,
                    page_number=page.page_number,
                    score_threshold=score_threshold,
                )
            )

        document = OCRDocument(
            filename=path.name,
            total_pages=total_pages,
            processed_pages=len(pages),
            truncated=len(pages) < total_pages,
            detector_model=self.settings.detector_model,
            recognizer_model=getattr(
                self.ocr_engine,
                "recognizer_label",
                self.settings.recognizer_model,
            ),
            device=self.ocr_engine.device,
            elapsed_seconds=round(time.perf_counter() - started_at, 3),
            pages=pages,
        )
        for consumer in self.document_consumers:
            consumer.consume(document)
        return document

    def analyze_contract(
        self,
        contract_text: str,
        api_key: str,
        model: str,
        progress_callback: OCRProgressCallback | None = None,
    ) -> str:
        return self.analyzer.analyze(
            contract_text=contract_text,
            api_key=api_key,
            model=model,
            progress_callback=progress_callback,
        )
