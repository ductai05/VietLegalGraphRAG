from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class NormalizedRelationship:
    raw_label: str
    edge_type: str


RELATIONSHIP_LABELS: Dict[str, str] = {
    "Văn bản căn cứ": "CITES_AS_BASIS",
    "Văn bản dẫn chiếu": "CITES",
    "Văn bản HD, QĐ chi tiết": "GUIDES_DETAIL",
    "Văn bản được HD, QĐ chi tiết": "IS_GUIDED_DETAILED_BY",
    "Văn bản sửa đổi": "AMENDS",
    "Văn bản được sửa đổi": "IS_AMENDED_BY",
    "Văn bản bổ sung": "SUPPLEMENTS",
    "Văn bản được bổ sung": "IS_SUPPLEMENTED_BY",
    "Văn bản quy định hết hiệu lực": "REPLACES_OR_EXPIRES",
    "Văn bản quy định hết hiệu lực 1 phần": "REPLACES_OR_EXPIRES",
    "Văn bản hết hiệu lực": "IS_REPLACED_OR_EXPIRED_BY",
    "Văn bản bị hết hiệu lực 1 phần": "IS_REPLACED_OR_EXPIRED_BY",
    "Văn bản đình chỉ 1 phần": "SUSPENDS",
    "Văn bản bị đình chỉ 1 phần": "IS_SUSPENDED_BY",
    "Văn bản liên quan khác": "RELATED_TO",
}


TIER_1_TYPES = frozenset({
    "Hiến pháp",
    "Bộ luật",
    "Luật",
    "Pháp lệnh",
    "Văn bản hợp nhất",
})

TIER_2_TYPES = frozenset({
    "Nghị định",
    "Thông tư",
    "Thông tư liên tịch",
    "Quyết định",
    "Nghị quyết",
    "Chỉ thị",
    "Hướng dẫn",
})

TIER_3_TYPES = frozenset({
    "Điều ước quốc tế",
    "Hiệp định",
    "Quy chế",
    "Quy định",
    "Văn bản WTO",
    "Văn bản khác",
})


NODE_FIELDS = ["id", "label", "name", "source_id", "properties_json"]
EDGE_FIELDS = ["id", "type", "source_id", "target_id", "raw_type", "properties_json"]

DOCUMENT_FIELDS = [
    "id",
    "doc_id",
    "document_number",
    "title",
    "legal_type",
    "legal_sectors",
    "sector_list",
    "issuing_authority",
    "issuance_date",
    "effect_date",
    "effectless_date",
    "effect_status",
    "signers",
    "source",
    "priority_tier",
]

CHUNK_FIELDS = [
    "id",
    "chunk_id",
    "doc_id",
    "chunk_type",
    "section_path",
    "procedure_name",
    "embed",
    "keyword_index",
    "parent_id",
    "prev_chunk_id",
    "next_chunk_id",
    "token_estimate",
    "quality_flags",
]


def normalize_relationship_label(raw_label: Any) -> NormalizedRelationship:
    label = clean_text(raw_label)
    return NormalizedRelationship(
        raw_label=label,
        edge_type=RELATIONSHIP_LABELS.get(label, "RELATED_TO"),
    )


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return re.sub(r"\s+", " ", text)


def is_present(value: Any) -> bool:
    return bool(clean_text(value))


def slugify(value: Any) -> str:
    text = clean_text(value)
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "unknown"


def split_multi_value(value: Any) -> List[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = re.split(r"\s*[,;]\s*", text)
    return [part for part in (clean_text(part) for part in parts) if part]


def priority_tier(legal_type: Any) -> str:
    value = clean_text(legal_type)
    if not value:
        return "unknown"
    if value in TIER_1_TYPES:
        return "tier_1"
    if value in TIER_2_TYPES:
        return "tier_2"
    if value in TIER_3_TYPES:
        return "tier_3"
    return "unknown"


def join_list(value: Any, separator: str = "|") -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Iterable):
        return separator.join(clean_text(item) for item in value if is_present(item))
    return clean_text(value)

