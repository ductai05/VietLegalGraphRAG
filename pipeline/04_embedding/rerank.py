"""Generic cross-encoder rerankers and legal passage formatting utilities."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Sequence

import polars as pl

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
PASSAGE_FIELDS = (
    "legal_type",
    "document_number",
    "title",
    "issuing_authority",
    "effect_status",
    "effect_date",
    "legal_sectors",
    "linh_vuc",
    "chunk_text",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item is not None)
    return str(value)


def format_legal_passage(metadata: dict[str, Any]) -> str:
    """Build the metadata-aware passage consumed by rerankers."""
    sectors = f"{_text(metadata.get('legal_sectors'))} / {_text(metadata.get('linh_vuc'))}"
    return (
        f"[Loại văn bản] {_text(metadata.get('legal_type'))}  "
        f"[Số hiệu] {_text(metadata.get('document_number'))}  "
        f"[Tiêu đề] {_text(metadata.get('title'))}  "
        f"[Cơ quan ban hành] {_text(metadata.get('issuing_authority'))}  "
        f"[Tình trạng hiệu lực] {_text(metadata.get('effect_status'))}  "
        f"[Ngày hiệu lực] {_text(metadata.get('effect_date'))}  "
        f"[Lĩnh vực] {sectors}  "
        f"[Nội dung] {_text(metadata.get('chunk_text'))}"
    )


class PassageLoader:
    """Hydrate candidate passages from chunks.parquet and Qdrant payload metadata."""

    def __init__(self, chunks_path: Path | None) -> None:
        self.chunks_path = chunks_path
        self.columns: list[str] = []
        if chunks_path is not None:
            schema = pl.scan_parquet(chunks_path).collect_schema()
            self.columns = ["chunk_id", *[field for field in PASSAGE_FIELDS if field in schema]]

    def build_passages(self, hits: Sequence[dict[str, Any]]) -> list[str]:
        chunk_ids = [str(hit["chunk_id"]) for hit in hits if hit.get("chunk_id")]
        rows: dict[str, dict[str, Any]] = {}
        if self.chunks_path is not None and chunk_ids:
            frame = (
                pl.scan_parquet(self.chunks_path)
                .filter(pl.col("chunk_id").is_in(chunk_ids))
                .select(self.columns)
                .collect()
            )
            rows = {str(row["chunk_id"]): row for row in frame.iter_rows(named=True)}

        passages = []
        for hit in hits:
            metadata = dict(hit.get("payload") or {})
            metadata.update(rows.get(str(hit.get("chunk_id")), {}))
            passages.append(format_legal_passage(metadata))
        return passages


class BaseReranker(ABC):
    """Interface for rerankers that score (query, passage_text) pairs."""

    model_name: str
    device: str

    @abstractmethod
    def score_pairs(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int = 8,
    ) -> list[float]:
        """Return one relevance score per (query, passage_text) pair."""


class BGEReranker(BaseReranker):
    """Hugging Face sequence-classification cross-encoder reranker."""

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        *,
        device: str | None = None,
        cache_dir: str | None = None,
        max_length: int = 1024,
    ) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.model_name = model_name
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.max_length = max_length
        dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name, cache_dir=cache_dir, trust_remote_code=True
        )
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            trust_remote_code=True,
            torch_dtype=dtype,
        )
        self.model.to(self.device)
        self.model.eval()
        logging.info("Loaded reranker %s on %s", model_name, self.device)

    def score_pairs(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int = 8,
    ) -> list[float]:
        if batch_size <= 0:
            raise ValueError("rerank batch size must be positive")
        scores: list[float] = []
        with self.torch.inference_mode():
            for start in range(0, len(pairs), batch_size):
                inputs = self.tokenizer(
                    pairs[start : start + batch_size],
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                    return_tensors="pt",
                ).to(self.device)
                logits = self.model(**inputs).logits.float().view(-1)
                scores.extend(float(score) for score in logits.cpu().tolist())
        if len(scores) != len(pairs):
            raise RuntimeError(
                f"Reranker returned {len(scores)} scores for {len(pairs)} pairs"
            )
        return scores


class QwenReranker(BGEReranker):
    """Sequence-classification Qwen rerankers using the same generic pair contract."""


def create_reranker(
    model_name: str = DEFAULT_RERANKER_MODEL,
    *,
    device: str | None = None,
    cache_dir: str | None = None,
) -> BaseReranker:
    reranker_class = QwenReranker if "qwen" in model_name.lower() else BGEReranker
    return reranker_class(model_name, device=device, cache_dir=cache_dir)
