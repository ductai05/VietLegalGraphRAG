"""Vietnamese tokenization helpers shared by ingest and query."""

from __future__ import annotations

from typing import Any
import functools

from src.normalizer import fold_vietnamese, text_value

_WORD_TOKENIZE = None


def _load_word_tokenize():
    global _WORD_TOKENIZE
    if _WORD_TOKENIZE is None:
        try:
            from underthesea import word_tokenize
        except ImportError as exc:
            raise ImportError(
                "underthesea is required for sparse retrieval tokenization. "
                "Install dependencies with `pip install -r requirements.txt`."
            ) from exc
        _WORD_TOKENIZE = word_tokenize
    return _WORD_TOKENIZE


@functools.lru_cache(maxsize=50000)
def tokenize_vi(value: Any) -> str:
    text = text_value(value)
    if not text:
        return ""
    word_tokenize = _load_word_tokenize()
    try:
        return word_tokenize(text, format="text")
    except TypeError:
        tokens = word_tokenize(text)
        return " ".join(str(token) for token in tokens)


def tokenize_section_path(value: Any) -> str:
    if isinstance(value, list):
        text = " > ".join(str(item) for item in value if item)
    else:
        text = text_value(value)
    return tokenize_vi(text)


def add_tokenized_fields(record: dict[str, Any]) -> dict[str, Any]:
    section_vi = tokenize_section_path(record.get("section_path"))
    chunk_vi = tokenize_vi(record.get("chunk_text"))
    title_vi = tokenize_vi(record.get("title"))
    procedure_vi = tokenize_vi(record.get("procedure_name"))
    authority_vi = tokenize_vi(record.get("issuing_authority"))
    contextual_vi = tokenize_vi(record.get("contextual_text"))
    record.update(
        {
            "chunk_text_vi": chunk_vi,
            "contextual_text_vi": contextual_vi,
            "title_vi": title_vi,
            "section_path_vi": section_vi,
            "procedure_name_vi": procedure_vi,
            "issuing_authority_vi": authority_vi,
            "chunk_text_folded": fold_vietnamese(chunk_vi),
            "title_folded": fold_vietnamese(title_vi),
            "section_path_folded": fold_vietnamese(section_vi),
            "procedure_name_folded": fold_vietnamese(procedure_vi),
            "issuing_authority_folded": fold_vietnamese(authority_vi),
        }
    )
    return record
