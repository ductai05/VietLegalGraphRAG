from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .models import OCRDocument


class DocumentConsumer(Protocol):
    """Extension point for future RAG, vector DB, or knowledge graph indexing."""

    def consume(self, document: OCRDocument) -> None:
        ...


class ContractAnalyzer(Protocol):
    def analyze(
        self,
        contract_text: str,
        api_key: str,
        model: str,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> str:
        ...
