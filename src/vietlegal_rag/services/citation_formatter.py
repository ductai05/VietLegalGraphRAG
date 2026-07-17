"""Rendering helpers for the legal-basis block shown under every answer.

Serves both the static LightRAG path and the agent path, so every key beyond
``chunk_id`` / ``doc_id`` / ``title`` / ``citation`` must stay optional.
"""
from __future__ import annotations

import re
from typing import Any

# IntentDetector.DOCUMENT_NUMBER_PATTERN plus "Đ": its ASCII-only [A-Z0-9-]
# class does not match the "NĐ-CP" in "15/2020/NĐ-CP", the most common decree
# suffix in the corpus.
DOCUMENT_NUMBER_PATTERN = re.compile(r"\b\d{1,4}/\d{4}/[A-ZĐ0-9-]+\b", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"\b\d{4}\b")
_CHUNK_ID_PREFIX = "chunk_id:"
_TITLE_FALLBACK_WORDS = 8

_CITATION_KEYS = ("document_number", "title", "section_path", "chunk_id")

_EFFECT_MARKERS = {
    "expired": " ⚠️ (Hết hiệu lực)",
    "superseded": " ⚠️ (Đã có phiên bản mới)",
}


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


def format_citations_block(citations: list[dict[str, Any]]) -> str:
    """Render the ``📚 Căn cứ pháp lý`` block, or ``""`` when nothing renders."""
    if not citations:
        return ""

    import html

    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for cite in citations:
        parsed = parse_citation(cite.get("citation") or "")
        section_path = parsed["section_path"]
        title = cite.get("title") or parsed["title"]
        if not title:
            continue

        dedup_key = (title, section_path)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        label = f"{section_path}, {title}" if section_path else title
        shortened_label = f"{section_path}, {shorten_title(title)}" if section_path else shorten_title(title)
        text = cite.get("text") or ""
        url = cite.get("url")

        # Extract domain for cleaner URL display
        source_link = ""
        if url:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                if domain.startswith("www."):
                    domain = domain[4:]
                source_link = f' <a href="{url}" target="_blank" rel="noopener noreferrer" class="text-xs text-blue-500 hover:underline hover:text-blue-600">({domain})</a>'
            except Exception:
                source_link = f' <a href="{url}" target="_blank" rel="noopener noreferrer" class="text-xs text-blue-500 hover:underline hover:text-blue-600">(Nguồn)</a>'

        if text:
            escaped_text = html.escape(text.strip())
            formatted_text = escaped_text.replace("\n", "<br>")
            
            # Format expanded metadata section
            metadata_lines = []
            if title:
                metadata_lines.append(f'<div class="mb-1 text-xs text-gray-500 font-semibold dark:text-gray-400">Văn bản: {html.escape(title)}</div>')
            
            metadata_badges = []
            effect = cite.get("effect_verdict")
            if effect == "expired":
                metadata_badges.append('<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300">⚠️ Hết hiệu lực</span>')
            elif effect == "superseded":
                metadata_badges.append('<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-300">⚠️ Đã có phiên bản mới</span>')
            
            summary = cite.get("summary")
            if summary:
                metadata_badges.append(f'<span class="text-xs text-gray-500 dark:text-gray-400">Tóm tắt: {html.escape(summary)}</span>')
            
            if metadata_badges:
                metadata_lines.append(f'<div class="flex flex-wrap gap-2 mb-2">{" &bull; ".join(metadata_badges)}</div>')
                
            metadata_html = "".join(metadata_lines)

            # Collapsible Details block, where the citation row is the summary itself
            rendered = (
                f'<details class="citation-details group mt-2 pl-3 border-l-2 border-gray-200 dark:border-gray-800">\n'
                f'<summary>[{len(lines) + 1}] {shortened_label}</summary>\n'
                f'<div class="mt-2 pl-2 border-l border-gray-100 dark:border-gray-900">\n'
                f'  {metadata_html}\n'
                f'  <div class="mt-1 text-sm text-gray-600 dark:text-gray-400 whitespace-pre-wrap leading-relaxed">{formatted_text}</div>\n'
                f'  {source_link}\n'
                f'</div>\n'
                f'</details>'
            )
            lines.append(rendered)
        else:
            rendered = f"[{shortened_label}]({url})" if url else shortened_label
            rendered += _EFFECT_MARKERS.get(cite.get("effect_verdict") or "", "")
            summary = cite.get("summary")
            if summary:
                rendered += f" — {summary}"
            lines.append(f"- **[{len(lines) + 1}]** {rendered}")

    if not lines:
        return ""
    return "\n\n---\n**📚 Căn cứ pháp lý:**\n" + "\n".join(lines) + "\n"
