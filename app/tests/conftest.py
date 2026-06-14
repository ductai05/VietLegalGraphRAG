from __future__ import annotations

from pathlib import Path

import fitz
import pytest


def create_pdf(
    path: Path,
    page_count: int = 1,
    width: int = 300,
    height: int = 200,
) -> Path:
    document = fitz.open()
    for index in range(page_count):
        page = document.new_page(width=width, height=height)
        page.insert_text((30, 60), f"Page {index + 1}")
    document.save(path)
    document.close()
    return path


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    return create_pdf(tmp_path / "contract.pdf", page_count=2)
