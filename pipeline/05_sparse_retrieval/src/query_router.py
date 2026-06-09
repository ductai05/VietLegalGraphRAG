"""Route sparse queries between exact document-number search and BM25."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.normalizer import normalize_document_number, text_value

INTERNAL_ID_RE = re.compile(r"^\d{5,}$")
DASH_CLASS = "[-\u2010-\u2015\u2212]"
VIET_UPPER = "\u0110"
VIET_LOWER = "\u0111"
DOC_NUMBER_RE = re.compile(
    rf"\b\d{{1,5}}\s*/\s*(?:\d{{4}}\s*/\s*)?"
    rf"[A-Za-z{VIET_UPPER}{VIET_LOWER}]{{1,10}}"
    rf"(?:\s*{DASH_CLASS}\s*[A-Za-z0-9{VIET_UPPER}{VIET_LOWER}]{{1,15}})*\b"
)
DOC_DASH_RE = re.compile(
    rf"\b\d{{1,5}}\s*{DASH_CLASS}\s*"
    rf"[A-Za-z{VIET_UPPER}{VIET_LOWER}]{{2,}}"
    rf"(?:\s*{DASH_CLASS}\s*[A-Za-z0-9{VIET_UPPER}{VIET_LOWER}]{{1,15}})*\b"
)
PREFIX_DOC_RE = re.compile(
    rf"\b[A-Za-z{VIET_UPPER}{VIET_LOWER}]{{2,}}\s*{DASH_CLASS}\s*\d{{1,5}}\b"
)


@dataclass(frozen=True)
class QueryRoute:
    kind: str
    normalized_document_number: str = ""
    internal_id: int | None = None


def looks_like_document_number(query: str) -> bool:
    return bool(extract_document_number(query))


def extract_document_number(query: str) -> str:
    text = text_value(query)
    if not text:
        return ""
    for pattern in (DOC_NUMBER_RE, DOC_DASH_RE, PREFIX_DOC_RE):
        match = pattern.search(text)
        if match:
            return match.group(0)
    if len(text) > 100:
        return ""
    has_digit = any(ch.isdigit() for ch in text)
    if not has_digit:
        return ""
    has_letter = re.search(rf"[A-Za-z{VIET_UPPER}{VIET_LOWER}]", text)
    if "/" in text and has_letter:
        return text
    if re.search(rf"\d+\s*{DASH_CLASS}\s*[A-Za-z{VIET_UPPER}{VIET_LOWER}]{{2,}}", text):
        return text
    if re.search(rf"[A-Z{VIET_UPPER}]{{2,}}\s*{DASH_CLASS}\s*\d+", text):
        return text
    return ""


def route_query(query: str) -> QueryRoute:
    text = text_value(query)
    doc_number = extract_document_number(text)
    if doc_number:
        return QueryRoute(
            kind="exact",
            normalized_document_number=normalize_document_number(doc_number),
        )
    if INTERNAL_ID_RE.match(text):
        return QueryRoute(kind="exact", internal_id=int(text))
    return QueryRoute(kind="keyword")
