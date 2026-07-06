"""Small text-cleaning helpers for the preprocessing stage.

This module is intentionally local to `02_preprocessing/clean` so it can be run
or imported from this folder without installing a global `pipeline` package.
"""

from __future__ import annotations

import re


HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
LEGAL_BREAK_RE = re.compile(
    r"(?=\b(?:Can cu|Xet|Theo de nghi|QUYET DINH|Dieu\s+\d+|"
    r"Chuong\s+[IVXLCDM\d]+|Muc\s+\d+|Phan\s+[IVXLCDM\d]+)\b)",
    re.IGNORECASE,
)


def normalize_whitespace(text: object) -> str:
    """Collapse horizontal whitespace and normalize newlines."""
    if text is None:
        return ""
    value = str(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def strip_simple_html(text: object) -> str:
    """Remove common HTML tags without adding a parser dependency."""
    value = "" if text is None else str(text)
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?is)<br\s*/?>", "\n", value)
    value = re.sub(r"(?is)</p\s*>", "\n", value)
    value = re.sub(r"(?is)<.*?>", " ", value)
    return normalize_whitespace(value)


def clean_legal_text(text: object) -> str:
    """Clean one legal document body while preserving readable line breaks."""
    value = "" if text is None else str(text)
    if HTML_TAG_RE.search(value[:5000]):
        value = strip_simple_html(value)
    else:
        value = normalize_whitespace(value)
    parts: list[str] = []
    for line in value.split("\n"):
        split_parts = [part.strip() for part in LEGAL_BREAK_RE.split(line) if part.strip()]
        parts.extend(split_parts or [line.strip()])
    return "\n".join(part for part in parts if part).strip()


if __name__ == "__main__":
    import sys

    print(clean_legal_text(sys.stdin.read()))
