"""Helpers for parsing and shortening legal citations emitted to Open WebUI.

Serves both the static LightRAG path and the agent path, so every key beyond
``chunk_id`` / ``doc_id`` / ``title`` / ``citation`` must stay optional.
"""
from __future__ import annotations

import re

# IntentDetector.DOCUMENT_NUMBER_PATTERN plus "Đ": its ASCII-only [A-Z0-9-]
# class does not match the "NĐ-CP" in "15/2020/NĐ-CP", the most common decree
# suffix in the corpus.
DOCUMENT_NUMBER_PATTERN = re.compile(r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"\b\d{4}\b")
_CHUNK_ID_PREFIX = "chunk_id:"
_TITLE_FALLBACK_WORDS = 8

_CITATION_KEYS = ("document_number", "title", "section_path", "chunk_id")

def parse_citation(citation: str) -> dict[str, str]:
    """Unpack the pipe-packed string built by ``elasticsearch_retriever.format_citation``.

    ``format_citation`` drops empty parts, so segment positions are not fixed —
    identify each field by shape rather than by index.
    """
    parsed = {key: "" for key in _CITATION_KEYS}
    if not citation or not isinstance(citation, str):
        return parsed

    segments = [part.strip() for part in citation.split(" | ")]
    remaining: list[str] = []
    for segment in segments:
        if not segment:
            continue
        if segment.startswith(_CHUNK_ID_PREFIX):
            parsed["chunk_id"] = segment[len(_CHUNK_ID_PREFIX) :].strip()
        else:
            remaining.append(segment)

    for segment in remaining:
        # fullmatch, not search: a title also contains the document number.
        if DOCUMENT_NUMBER_PATTERN.fullmatch(segment):
            parsed["document_number"] = segment
            remaining.remove(segment)
            break

    if remaining:
        title = max(remaining, key=len)
        parsed["title"] = title
        remaining.remove(title)

    if remaining:
        parsed["section_path"] = remaining[0]

    return parsed


def shorten_title(title: str) -> str:
    """Reduce a long official title to its legal-type + number prefix."""
    if not title or not title.strip():
        return title or ""

    text = title.strip()
    match = DOCUMENT_NUMBER_PATTERN.search(text)
    if match:
        return text[: match.end()].strip()

    # Named codes carry a year instead of a document number.
    match = _YEAR_PATTERN.search(text)
    if match:
        return text[: match.end()].strip()

    words = text.split()
    if len(words) > _TITLE_FALLBACK_WORDS:
        return " ".join(words[:_TITLE_FALLBACK_WORDS])
    return text


def format_citations_block(citations: list[dict]) -> str:
    """Format a list of citations into a Markdown block with visual summaries.

    Serves both the static path and the agent path.
    """
    if not citations:
        return ""

    seen = set()
    unique_entries = []

    for cite in citations:
        if not isinstance(cite, dict):
            continue

        citation_str = cite.get("citation", "")
        parsed = parse_citation(citation_str) if citation_str else {}

        # Use title from cite dict or parsed dict
        title = cite.get("title") or parsed.get("title", "")
        if not title:
            continue

        section_path = parsed.get("section_path", "")
        short_title = shorten_title(title)

        dedupe_key = (short_title, section_path)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        unique_entries.append({
            "cite": cite,
            "parsed": parsed,
            "short_title": short_title,
            "section_path": section_path,
        })

    if not unique_entries:
        return ""

    lines = ["📚 Căn cứ pháp lý:\n"]
    for i, entry in enumerate(unique_entries, start=1):
        cite = entry["cite"]
        short_title = entry["short_title"]
        section_path = entry["section_path"]

        url = cite.get("url")
        effect_verdict = cite.get("effect_verdict")
        summary = cite.get("summary")
        text = cite.get("text")

        if section_path:
            link_text = f"{section_path}, {short_title}"
        else:
            link_text = short_title

        # Check if text is present to determine if we render a <details> block
        if text:
            # Building summary link
            if url:
                summary_link = f'<a href="{url}">{link_text}</a>'
            else:
                summary_link = link_text

            # Building verdict marker
            verdict_span = ""
            if effect_verdict == "expired":
                verdict_span = ' <span class="effect-verdict">⚠️ Hết hiệu lực</span>'
            elif effect_verdict == "superseded":
                verdict_span = ' <span class="effect-verdict">⚠️ Đã có phiên bản mới</span>'

            details_html = f'<details><summary>{summary_link}{verdict_span}</summary>'
            if summary:
                details_html += f'<p>Tóm tắt: {summary}</p>'
            details_html += f'<p>{text}</p></details>'

            lines.append(f"- **[{i}]** {details_html}")
        else:
            # Standard markdown format without <details>
            if url:
                link_part = f"[{link_text}]({url})"
            else:
                link_part = link_text

            verdict_part = ""
            if effect_verdict == "expired":
                verdict_part = " ⚠️ (Hết hiệu lực)"
            elif effect_verdict == "superseded":
                verdict_part = " ⚠️ (Đã có phiên bản mới)"

            summary_part = f" — {summary}" if summary else ""

            lines.append(f"- **[{i}]** {link_part}{verdict_part}{summary_part}")

    return "\n".join(lines)

