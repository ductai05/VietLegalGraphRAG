from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class NormalizedRelationship:
    raw_label: str
    edge_type: str
    reverse_direction: bool = False


RELATIONSHIP_LABELS: Dict[str, Tuple[str, bool]] = {
    "V\u0103n b\u1ea3n c\u0103n c\u1ee9": ("CITES", False),
    "V\u0103n b\u1ea3n d\u1eabn chi\u1ebfu": ("CITES", False),
    "V\u0103n b\u1ea3n HD, Q\u0110 chi ti\u1ebft": ("GUIDELINES", False),
    "V\u0103n b\u1ea3n \u0111\u01b0\u1ee3c HD, Q\u0110 chi ti\u1ebft": ("GUIDELINES", True),
    "V\u0103n b\u1ea3n s\u1eeda \u0111\u1ed5i": ("AMENDS", False),
    "V\u0103n b\u1ea3n \u0111\u01b0\u1ee3c s\u1eeda \u0111\u1ed5i": ("AMENDS", True),
    "V\u0103n b\u1ea3n b\u1ed5 sung": ("AMENDS", False),
    "V\u0103n b\u1ea3n \u0111\u01b0\u1ee3c b\u1ed5 sung": ("AMENDS", True),
    "V\u0103n b\u1ea3n quy \u0111\u1ecbnh h\u1ebft hi\u1ec7u l\u1ef1c": ("REPEALS", False),
    "V\u0103n b\u1ea3n quy \u0111\u1ecbnh h\u1ebft hi\u1ec7u l\u1ef1c 1 ph\u1ea7n": ("REPEALS", False),
    "V\u0103n b\u1ea3n h\u1ebft hi\u1ec7u l\u1ef1c": ("REPEALS", True),
    "V\u0103n b\u1ea3n b\u1ecb h\u1ebft hi\u1ec7u l\u1ef1c 1 ph\u1ea7n": ("REPEALS", True),
    "V\u0103n b\u1ea3n \u0111\u00ecnh ch\u1ec9 1 ph\u1ea7n": ("REPEALS", False),
    "V\u0103n b\u1ea3n b\u1ecb \u0111\u00ecnh ch\u1ec9 1 ph\u1ea7n": ("REPEALS", True),
    "V\u0103n b\u1ea3n li\u00ean quan kh\u00e1c": ("CITES", False),
}


TIER_1_TYPES = frozenset({
    "Hi\u1ebfn ph\u00e1p",
    "B\u1ed9 lu\u1eadt",
    "Lu\u1eadt",
    "Ph\u00e1p l\u1ec7nh",
    "V\u0103n b\u1ea3n h\u1ee3p nh\u1ea5t",
})

TIER_2_TYPES = frozenset({
    "Ngh\u1ecb \u0111\u1ecbnh",
    "Th\u00f4ng t\u01b0",
    "Th\u00f4ng t\u01b0 li\u00ean t\u1ecbch",
    "Quy\u1ebft \u0111\u1ecbnh",
    "Ngh\u1ecb quy\u1ebft",
    "Ch\u1ec9 th\u1ecb",
    "H\u01b0\u1edbng d\u1eabn",
})

TIER_3_TYPES = frozenset({
    "\u0110i\u1ec1u \u01b0\u1edbc qu\u1ed1c t\u1ebf",
    "Hi\u1ec7p \u0111\u1ecbnh",
    "Quy ch\u1ebf",
    "Quy \u0111\u1ecbnh",
    "V\u0103n b\u1ea3n WTO",
    "V\u0103n b\u1ea3n kh\u00e1c",
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
    edge_type, reverse_direction = RELATIONSHIP_LABELS.get(label, ("CITES", False))
    return NormalizedRelationship(
        raw_label=label,
        edge_type=edge_type,
        reverse_direction=reverse_direction,
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
    text = text.replace("\u0110", "D").replace("\u0111", "d")
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
