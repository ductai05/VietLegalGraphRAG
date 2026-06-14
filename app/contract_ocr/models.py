from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class OCRLine:
    text: str
    confidence: float
    polygon: list[list[int]] = field(default_factory=list)


@dataclass(slots=True)
class OCRPage:
    page_number: int
    width: int
    height: int
    lines: list[OCRLine] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text.strip())


@dataclass(slots=True)
class OCRDocument:
    filename: str
    total_pages: int
    processed_pages: int
    truncated: bool
    detector_model: str
    recognizer_model: str
    device: str
    elapsed_seconds: float
    pages: list[OCRPage] = field(default_factory=list)

    @property
    def text(self) -> str:
        sections = []
        for page in self.pages:
            sections.append(f"=== Trang {page.page_number} ===\n{page.text}".strip())
        return "\n\n".join(section for section in sections if section)

    @property
    def line_count(self) -> int:
        return sum(len(page.lines) for page in self.pages)

    @property
    def average_confidence(self) -> float:
        scores = [
            line.confidence
            for page in self.pages
            for line in page.lines
        ]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["line_count"] = self.line_count
        data["average_confidence"] = round(self.average_confidence, 4)
        return data

    def table_rows(self) -> list[list[Any]]:
        return [
            [
                page.page_number,
                index,
                line.text,
                round(line.confidence, 4),
            ]
            for page in self.pages
            for index, line in enumerate(page.lines, start=1)
        ]
