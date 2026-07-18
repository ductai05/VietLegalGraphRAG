"""Hermetic tests for the citation rendering helpers.

Pure functions: no live Elasticsearch, Neo4j, or LLM calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG_SERVICES = ROOT / "src" / "vietlegal_rag" / "services"
if str(RAG_SERVICES) not in sys.path:
    sys.path.insert(0, str(RAG_SERVICES))

FULL_TITLE = (
    "Nghị định 15/2020/NĐ-CP quy định xử phạt vi phạm hành chính trong lĩnh vực "
    "bưu chính, viễn thông, tần số vô tuyến điện, công nghệ thông tin và giao dịch điện tử"
)


# ----------------------------------------------------------------------
# parse_citation
# ----------------------------------------------------------------------


def test_parse_citation_all_four_segments() -> None:
    from citation_formatter import parse_citation

    citation = f"15/2020/NĐ-CP | {FULL_TITLE} | Điều 101 | chunk_id: chunk:nd15:000101"
    parsed = parse_citation(citation)

    assert parsed["document_number"] == "15/2020/NĐ-CP"
    assert parsed["title"] == FULL_TITLE
    assert parsed["section_path"] == "Điều 101"
    assert parsed["chunk_id"] == "chunk:nd15:000101"


def test_parse_citation_without_section_path() -> None:
    from citation_formatter import parse_citation

    # format_citation drops empty parts, so this arrives as three segments.
    parsed = parse_citation(f"15/2020/NĐ-CP | {FULL_TITLE} | chunk_id: chunk:nd15:000001")

    assert parsed["document_number"] == "15/2020/NĐ-CP"
    assert parsed["title"] == FULL_TITLE
    assert parsed["section_path"] == ""
    assert parsed["chunk_id"] == "chunk:nd15:000001"


def test_parse_citation_without_document_number() -> None:
    from citation_formatter import parse_citation

    parsed = parse_citation("Bộ luật Lao động 2019 | Điều 25 | chunk_id: chunk:bllb:000025")

    assert parsed["document_number"] == ""
    assert parsed["title"] == "Bộ luật Lao động 2019"
    assert parsed["section_path"] == "Điều 25"
    assert parsed["chunk_id"] == "chunk:bllb:000025"


def test_parse_citation_garbage_without_pipes_never_raises() -> None:
    from citation_formatter import parse_citation

    parsed = parse_citation("hoàn toàn không đúng định dạng")

    assert parsed["title"] == "hoàn toàn không đúng định dạng"
    assert parsed["document_number"] == ""
    assert parsed["section_path"] == ""
    assert parsed["chunk_id"] == ""


def test_parse_citation_empty_input_returns_empty_keys() -> None:
    from citation_formatter import parse_citation

    assert parse_citation("") == {
        "document_number": "",
        "title": "",
        "section_path": "",
        "chunk_id": "",
    }


# ----------------------------------------------------------------------
# shorten_title
# ----------------------------------------------------------------------


def test_shorten_title_numbered_document() -> None:
    from citation_formatter import shorten_title

    assert shorten_title(FULL_TITLE) == "Nghị định 15/2020/NĐ-CP"


def test_shorten_title_named_code_falls_back_to_year() -> None:
    from citation_formatter import shorten_title

    assert shorten_title("Bộ luật Lao động 2019 quy định về hợp đồng") == "Bộ luật Lao động 2019"


def test_shorten_title_without_number_or_year_truncates_to_eight_words() -> None:
    from citation_formatter import shorten_title

    title = "một hai ba bốn năm sáu bảy tám chín mười"

    assert shorten_title(title) == "một hai ba bốn năm sáu bảy tám"


def test_shorten_title_never_returns_empty_for_short_title() -> None:
    from citation_formatter import shorten_title

    assert shorten_title("Luật Doanh nghiệp") == "Luật Doanh nghiệp"


# ----------------------------------------------------------------------
# format_citations_block
# ----------------------------------------------------------------------


def _static_path_citation() -> dict[str, str]:
    """The shape LightRAGService.stream_answer produces: no url/verdict/summary."""
    return {
        "chunk_id": "chunk:nd15:000101",
        "doc_id": "nd15",
        "title": FULL_TITLE,
        "citation": f"15/2020/NĐ-CP | {FULL_TITLE} | Điều 101 | chunk_id: chunk:nd15:000101",
    }


def test_format_citations_block_static_path_renders_plain_text() -> None:
    from citation_formatter import format_citations_block

    cite = _static_path_citation()
    cite["text"] = "Noi dung phap ly"
    block = format_citations_block([cite])

    assert "📚 Căn cứ pháp lý" in block
    assert "Điều 101, Nghị định 15/2020/NĐ-CP" in block
    assert "<details" in block
    assert "Noi dung phap ly" in block


def test_format_citations_block_static_path_fallback_without_text() -> None:
    from citation_formatter import format_citations_block

    block = format_citations_block([_static_path_citation()])

    assert "📚 Căn cứ pháp lý" in block
    assert "Điều 101" in block
    assert "<span" not in block


def test_format_citations_block_never_leaks_chunk_id() -> None:
    from citation_formatter import format_citations_block

    block = format_citations_block([_static_path_citation()])

    assert "chunk_id" not in block
    assert "chunk:nd15:000101" not in block


def test_format_citations_block_agent_path_renders_link_marker_and_summary() -> None:
    from citation_formatter import format_citations_block

    cite = _static_path_citation()
    cite.update(
        {
            "url": "https://vanban.chinhphu.vn/nd15",
            "effect_verdict": "expired",
            "summary": "Quy định về trách nhiệm sử dụng dịch vụ mạng xã hội.",
            "text": "Noi dung phap ly",
        }
    )

    block = format_citations_block([cite])

    assert 'href="https://vanban.chinhphu.vn/nd15"' in block
    assert "Noi dung phap ly" in block
    assert "⚠️ Hết hiệu lực" in block
    assert "Tóm tắt: Quy định về trách nhiệm sử dụng dịch vụ mạng xã hội." in block


def test_format_citations_block_agent_path_fallback_without_text() -> None:
    from citation_formatter import format_citations_block

    cite = _static_path_citation()
    cite.update(
        {
            "url": "https://vanban.chinhphu.vn/nd15",
            "effect_verdict": "expired",
            "summary": "Quy định về trách nhiệm sử dụng dịch vụ mạng xã hội.",
        }
    )

    block = format_citations_block([cite])

    assert "[Điều 101, Nghị định 15/2020/NĐ-CP]" in block
    assert "https://vanban.chinhphu.vn/nd15" in block
    assert "⚠️ (Hết hiệu lực)" in block


def test_format_citations_block_superseded_marker() -> None:
    from citation_formatter import format_citations_block

    cite = _static_path_citation()
    cite["effect_verdict"] = "superseded"

    assert "⚠️ (Đã có phiên bản mới)" in format_citations_block([cite])


def test_format_citations_block_no_marker_for_in_force() -> None:
    from citation_formatter import format_citations_block

    cite = _static_path_citation()
    cite["effect_verdict"] = "in_force"

    assert "⚠️" not in format_citations_block([cite])


def test_format_citations_block_dedupes_by_short_title_and_section() -> None:
    from citation_formatter import format_citations_block

    first = _static_path_citation()
    duplicate = _static_path_citation()
    duplicate["chunk_id"] = "chunk:nd15:000102"

    block = format_citations_block([first, duplicate])

    assert block.count("Nghị định 15/2020/NĐ-CP") == 1
    assert "**[2]**" not in block


def test_format_citations_block_numbers_distinct_entries_sequentially() -> None:
    from citation_formatter import format_citations_block

    second = _static_path_citation()
    second["citation"] = f"15/2020/NĐ-CP | {FULL_TITLE} | Điều 102 | chunk_id: chunk:nd15:000102"

    block = format_citations_block([_static_path_citation(), second])

    assert "- **[1]** Điều 101," in block
    assert "- **[2]** Điều 102," in block


def test_format_citations_block_empty_input_returns_empty_string() -> None:
    from citation_formatter import format_citations_block

    assert format_citations_block([]) == ""


def test_format_citations_block_all_filtered_returns_empty_string() -> None:
    from citation_formatter import format_citations_block

    assert format_citations_block([{"chunk_id": "c1", "doc_id": "d1"}]) == ""
