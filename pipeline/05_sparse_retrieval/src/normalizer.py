"""Normalize sparse chunk and metadata rows before Elasticsearch ingestion."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any

import polars as pl

DASH_RE = re.compile(r"[\u2010-\u2015\u2212]+")
SPACE_RE = re.compile(r"\s+")

SPARSE_SCHEMA = {
    "chunk_id": pl.Utf8,
    "doc_id": pl.Int64,
    "source": pl.Utf8,
    "chunk_text": pl.Utf8,
    "contextual_text": pl.Utf8,
    "chunk_type": pl.Utf8,
    "section_path": pl.List(pl.Utf8),
    "procedure_name": pl.Utf8,
    "embed": pl.Boolean,
    "keyword_index": pl.Boolean,
    "parent_id": pl.Utf8,
    "prev_chunk_id": pl.Utf8,
    "next_chunk_id": pl.Utf8,
    "table_id": pl.Utf8,
    "raw_table_id": pl.Utf8,
    "summary_of": pl.Utf8,
    "answer_source": pl.Utf8,
    "do_not_answer_from_summary": pl.Boolean,
    "token_estimate": pl.Int64,
    "char_count": pl.Int64,
    "quality_flags": pl.List(pl.Utf8),
    "table_columns": pl.List(pl.Utf8),
    "document_number": pl.Utf8,
    "document_number_norm": pl.Utf8,
    "title": pl.Utf8,
    "legal_type": pl.Utf8,
    "legal_sectors": pl.List(pl.Utf8),
    "issuing_authority": pl.Utf8,
    "issuance_date": pl.Utf8,
    "effect_date": pl.Utf8,
    "effectless_date": pl.Utf8,
    "effect_status": pl.Utf8,
    "linh_vuc": pl.Utf8,
    "nganh": pl.Utf8,
    "pham_vi": pl.Utf8,
    "expansion_status": pl.Utf8,
    "chunk_text_vi": pl.Utf8,
    "contextual_text_vi": pl.Utf8,
    "title_vi": pl.Utf8,
    "section_path_vi": pl.Utf8,
    "procedure_name_vi": pl.Utf8,
    "issuing_authority_vi": pl.Utf8,
    "chunk_text_folded": pl.Utf8,
    "title_folded": pl.Utf8,
    "section_path_folded": pl.Utf8,
    "procedure_name_folded": pl.Utf8,
    "issuing_authority_folded": pl.Utf8,
}

METADATA_COLUMNS = [
    "id",
    "document_number",
    "title",
    "legal_type",
    "legal_sectors",
    "issuing_authority",
    "issuance_date",
    "effect_date",
    "effectless_date",
    "effect_status",
    "linh_vuc",
    "nganh",
    "pham_vi",
    "source",
]


def text_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, float) and value != value:
        return default
    if hasattr(value, "item"):
        try:
            return text_value(value.item(), default=default)
        except Exception:
            pass
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "<na>", "none", "null"}:
        return default
    return text


def bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, float) and value != value:
        return default
    if hasattr(value, "item"):
        try:
            return bool_value(value.item(), default=default)
        except Exception:
            pass
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    try:
        return bool(value)
    except Exception:
        return default


def int_value(value: Any, default: int = 0) -> int:
    if hasattr(value, "item"):
        try:
            return int_value(value.item(), default=default)
        except Exception:
            pass
    try:
        return int(value)
    except Exception:
        return default


def ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, float) and value != value:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := text_value(item))]
    if isinstance(value, (tuple, set)):
        return [text for item in value if (text := text_value(item))]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                return ensure_list(parsed)
            except Exception:
                return [stripped]
        return [stripped]
    text = text_value(value)
    return [text] if text else []


def split_keyword_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return ensure_list(value)
    text = text_value(value)
    if not text:
        return []
    if text.startswith("["):
        return ensure_list(text)
    parts = re.split(r"[,;]", text)
    return [part.strip() for part in parts if part.strip()]


def normalize_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = text_value(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return text


def normalize_document_number(value: Any) -> str:
    text = text_value(value)
    if not text:
        return ""
    text = DASH_RE.sub("-", text)
    text = SPACE_RE.sub("", text)
    return text.lower()


def fold_vietnamese(text: Any) -> str:
    value = text_value(text).replace("\u0110", "D").replace("\u0111", "d")
    normalized = unicodedata.normalize("NFD", value)
    folded = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", folded).lower()


def normalize_sparse_record(row: dict[str, Any]) -> dict[str, Any]:
    legal_sectors = split_keyword_list(row.get("legal_sectors"))
    if not legal_sectors:
        legal_sectors = split_keyword_list(row.get("linh_vuc") or row.get("nganh"))
    chunk_text = text_value(row.get("chunk_text"))
    contextual_text = text_value(row.get("contextual_text")) or chunk_text
    doc_number = text_value(row.get("document_number"))
    return {
        "chunk_id": text_value(row.get("chunk_id")),
        "doc_id": int_value(row.get("doc_id"), default=0),
        "source": text_value(row.get("source")),
        "chunk_text": chunk_text,
        "contextual_text": contextual_text,
        "chunk_type": text_value(row.get("chunk_type")),
        "section_path": ensure_list(row.get("section_path")),
        "procedure_name": text_value(row.get("procedure_name")),
        "embed": bool_value(row.get("embed"), default=False),
        "keyword_index": bool_value(row.get("keyword_index"), default=False),
        "parent_id": text_value(row.get("parent_id")),
        "prev_chunk_id": text_value(row.get("prev_chunk_id")),
        "next_chunk_id": text_value(row.get("next_chunk_id")),
        "table_id": text_value(row.get("table_id")),
        "raw_table_id": text_value(row.get("raw_table_id")),
        "summary_of": text_value(row.get("summary_of")),
        "answer_source": text_value(row.get("answer_source")),
        "do_not_answer_from_summary": bool_value(row.get("do_not_answer_from_summary")),
        "token_estimate": int_value(row.get("token_estimate")),
        "char_count": int_value(row.get("char_count"), default=len(chunk_text)),
        "quality_flags": ensure_list(row.get("quality_flags")),
        "table_columns": ensure_list(row.get("table_columns")),
        "document_number": doc_number,
        "document_number_norm": normalize_document_number(doc_number),
        "title": text_value(row.get("title")),
        "legal_type": text_value(row.get("legal_type")),
        "legal_sectors": legal_sectors,
        "issuing_authority": text_value(row.get("issuing_authority")),
        "issuance_date": normalize_date(row.get("issuance_date")),
        "effect_date": normalize_date(row.get("effect_date")),
        "effectless_date": normalize_date(row.get("effectless_date")),
        "effect_status": text_value(row.get("effect_status")),
        "linh_vuc": text_value(row.get("linh_vuc")),
        "nganh": text_value(row.get("nganh")),
        "pham_vi": text_value(row.get("pham_vi")),
        "expansion_status": text_value(row.get("expansion_status"), default="ok"),
    }


def string_expr(name: str, available: set[str], alias: str | None = None) -> pl.Expr:
    output = alias or name
    if name in available:
        return pl.col(name).cast(pl.Utf8, strict=False).fill_null("").alias(output)
    return pl.lit("").alias(output)


def bool_expr(name: str, available: set[str], default: bool = False) -> pl.Expr:
    if name in available:
        return pl.col(name).cast(pl.Boolean, strict=False).fill_null(default).alias(name)
    return pl.lit(default).alias(name)


def int_expr(name: str, available: set[str]) -> pl.Expr:
    if name in available:
        return pl.col(name).cast(pl.Int64, strict=False).fill_null(0).alias(name)
    return pl.lit(0).alias(name)


def list_expr(name: str, available: set[str]) -> pl.Expr:
    if name in available:
        return pl.col(name).alias(name)
    return pl.lit([], dtype=pl.List(pl.Utf8)).alias(name)
