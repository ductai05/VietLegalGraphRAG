from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import fitz
import numpy as np

from .exceptions import PDFValidationError


@dataclass(slots=True)
class RenderedPage:
    page_number: int
    image: np.ndarray


class PDFRenderer:
    def __init__(
        self,
        max_upload_mb: int,
        max_pages: int,
        max_dpi: int,
    ) -> None:
        self.max_upload_bytes = max_upload_mb * 1024 * 1024
        self.max_pages = max_pages
        self.max_dpi = max_dpi

    def inspect(self, pdf_path: str | Path) -> tuple[Path, int]:
        path = Path(pdf_path)
        if not path.is_file():
            raise PDFValidationError("Không tìm thấy tệp PDF đã tải lên.")
        if path.suffix.lower() != ".pdf":
            raise PDFValidationError("Ứng dụng chỉ chấp nhận tệp có đuôi .pdf.")
        if path.stat().st_size > self.max_upload_bytes:
            max_mb = self.max_upload_bytes // (1024 * 1024)
            raise PDFValidationError(
                f"Tệp vượt quá giới hạn {max_mb} MB của máy chủ."
            )

        try:
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise PDFValidationError("Tệp tải lên không có định dạng PDF hợp lệ.")
            with fitz.open(path) as document:
                if document.needs_pass:
                    raise PDFValidationError(
                        "PDF đang được bảo vệ bằng mật khẩu. Hãy mở khóa trước khi tải lên."
                    )
                if document.page_count < 1:
                    raise PDFValidationError("PDF không có trang nào.")
                return path, document.page_count
        except PDFValidationError:
            raise
        except (fitz.FileDataError, RuntimeError, ValueError) as exc:
            raise PDFValidationError(f"Không thể đọc PDF: {exc}") from exc

    def iter_pages(
        self,
        pdf_path: str | Path,
        dpi: int,
        requested_pages: int,
    ) -> Iterator[RenderedPage]:
        path, total_pages = self.inspect(pdf_path)
        safe_dpi = min(max(96, int(dpi)), self.max_dpi)
        pages_to_process = min(total_pages, requested_pages, self.max_pages)
        zoom = safe_dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        try:
            with fitz.open(path) as document:
                for page_index in range(pages_to_process):
                    page = document.load_page(page_index)
                    pixmap = page.get_pixmap(
                        matrix=matrix,
                        colorspace=fitz.csRGB,
                        alpha=False,
                    )
                    image = np.frombuffer(
                        pixmap.samples,
                        dtype=np.uint8,
                    ).reshape(pixmap.height, pixmap.width, 3)
                    yield RenderedPage(
                        page_number=page_index + 1,
                        image=image.copy(),
                    )
        except (fitz.FileDataError, RuntimeError, ValueError) as exc:
            raise PDFValidationError(f"Lỗi khi render PDF: {exc}") from exc
