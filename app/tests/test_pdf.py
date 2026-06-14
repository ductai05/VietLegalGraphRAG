from pathlib import Path

import fitz
import pytest

from contract_ocr.exceptions import PDFValidationError
from contract_ocr.pdf import PDFRenderer

from .conftest import create_pdf


def test_inspect_returns_path_and_page_count(sample_pdf: Path) -> None:
    renderer = PDFRenderer(max_upload_mb=5, max_pages=10, max_dpi=200)

    path, page_count = renderer.inspect(sample_pdf)

    assert path == sample_pdf
    assert page_count == 2


def test_renderer_streams_requested_pages(sample_pdf: Path) -> None:
    renderer = PDFRenderer(max_upload_mb=5, max_pages=10, max_dpi=200)

    pages = list(renderer.iter_pages(sample_pdf, dpi=120, requested_pages=1))

    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert pages[0].image.ndim == 3
    assert pages[0].image.shape[2] == 3


def test_renderer_rejects_non_pdf(tmp_path: Path) -> None:
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("not a pdf", encoding="utf-8")
    renderer = PDFRenderer(max_upload_mb=5, max_pages=10, max_dpi=200)

    with pytest.raises(PDFValidationError, match="định dạng PDF"):
        renderer.inspect(fake_pdf)


def test_renderer_rejects_missing_file_and_wrong_extension(tmp_path: Path) -> None:
    renderer = PDFRenderer(max_upload_mb=5, max_pages=10, max_dpi=200)

    with pytest.raises(PDFValidationError, match="Không tìm thấy"):
        renderer.inspect(tmp_path / "missing.pdf")

    text_file = tmp_path / "contract.txt"
    text_file.write_text("%PDF-fake", encoding="utf-8")
    with pytest.raises(PDFValidationError, match=r"\.pdf"):
        renderer.inspect(text_file)


def test_renderer_rejects_file_over_size_limit(sample_pdf: Path) -> None:
    renderer = PDFRenderer(max_upload_mb=0, max_pages=10, max_dpi=200)

    with pytest.raises(PDFValidationError, match="giới hạn 0 MB"):
        renderer.inspect(sample_pdf)


def test_renderer_rejects_password_protected_pdf(tmp_path: Path) -> None:
    source = create_pdf(tmp_path / "source.pdf")
    encrypted = tmp_path / "encrypted.pdf"
    with fitz.open(source) as document:
        document.save(
            encrypted,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="secret",
        )
    renderer = PDFRenderer(max_upload_mb=5, max_pages=10, max_dpi=200)

    with pytest.raises(PDFValidationError, match="mật khẩu"):
        renderer.inspect(encrypted)


def test_renderer_clamps_dpi_and_page_limit(tmp_path: Path) -> None:
    pdf_path = create_pdf(
        tmp_path / "square.pdf",
        page_count=3,
        width=72,
        height=72,
    )
    renderer = PDFRenderer(max_upload_mb=5, max_pages=2, max_dpi=144)

    low_dpi_pages = list(
        renderer.iter_pages(pdf_path, dpi=10, requested_pages=3)
    )
    high_dpi_pages = list(
        renderer.iter_pages(pdf_path, dpi=999, requested_pages=3)
    )

    assert len(low_dpi_pages) == 2
    assert low_dpi_pages[0].image.shape == (96, 96, 3)
    assert high_dpi_pages[0].image.shape == (144, 144, 3)
