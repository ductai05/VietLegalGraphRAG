"""Shared Elasticsearch contracts for ingest and dense retrieval."""

from __future__ import annotations

import math
import os
from typing import Any

import numpy as np

from embedding_common import PAYLOAD_FIELDS, VECTOR_SIZE, stable_point_id

INTEGER_FIELDS = {
    "issuance_date_ts",
    "effect_date_ts",
    "effectless_date_ts",
}
BOOLEAN_FIELDS = {"do_not_answer_from_summary"}
TEXT_FIELDS = {"title", "procedure_name"}


def resolve_credentials(
    cloud_id: str | None = None,
    api_key: str | None = None,
    url: str | None = None,
) -> tuple[str | None, str | None, str]:
    """Resolve Elastic Cloud ID or URL credentials and API key."""
    resolved_cloud_id = cloud_id or os.environ.get("ELASTIC_CLOUD_ID")
    resolved_url = url or os.environ.get("ELASTICSEARCH_URL") or os.environ.get("ELASTIC_URL")
    resolved_api_key = (
        api_key
        or os.environ.get("ELASTICSEARCH_API_KEY")
        or os.environ.get("ELASTIC_API_KEY")
    )
    if not resolved_cloud_id and not resolved_url:
        raise ValueError(
            "Missing Elasticsearch credentials: Provide cloud_id or url "
            "(or set ELASTIC_CLOUD_ID or ELASTICSEARCH_URL environment variables)."
        )
    if not resolved_api_key:
        raise ValueError(
            "Missing Elasticsearch API key: Pass CLI arguments or set ELASTICSEARCH_API_KEY or ELASTIC_API_KEY."
        )
    return resolved_cloud_id, resolved_url, resolved_api_key


def _keyword_mapping() -> dict[str, Any]:
    return {"type": "keyword", "ignore_above": 8192}


def _text_mapping() -> dict[str, Any]:
    return {
        "type": "text",
        "fields": {"keyword": {"type": "keyword", "ignore_above": 2048}},
    }


def build_index_definition(
    number_of_shards: int,
    number_of_replicas: int = 0,
) -> dict[str, Any]:
    """Return the versioned legal chunk mapping used during initial ingest."""
    if number_of_shards <= 0:
        raise ValueError("number_of_shards must be positive")
    if number_of_replicas < 0:
        raise ValueError("number_of_replicas cannot be negative")

    properties: dict[str, Any] = {
        field: (_text_mapping() if field in TEXT_FIELDS else _keyword_mapping())
        for field in PAYLOAD_FIELDS
    }
    properties["doc_id"] = _keyword_mapping()
    for field in INTEGER_FIELDS:
        properties[field] = {"type": "long"}
    for field in BOOLEAN_FIELDS:
        properties[field] = {"type": "boolean"}
    properties["vector"] = {
        "type": "dense_vector",
        "dims": VECTOR_SIZE,
        "index": True,
        "similarity": "cosine",
    }
    return {
        "settings": {
            "index": {
                "number_of_shards": number_of_shards,
                "number_of_replicas": number_of_replicas,
                "refresh_interval": "-1",
            }
        },
        "mappings": {
            "dynamic": "strict",
            "properties": properties,
        },
    }


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, list):
        return [item for item in (_normalize_value(item) for item in value) if item is not None]
    if isinstance(value, dict):
        return {
            str(key): normalized
            for key, item in value.items()
            if (normalized := _normalize_value(item)) is not None
        }
    return value


def _normalize_payload_field(field: str, value: Any) -> Any:
    value = _normalize_value(value)
    if value is None:
        return None
    if field == "doc_id":
        return str(value)
    if field in INTEGER_FIELDS:
        return int(value)
    if field in BOOLEAN_FIELDS:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
            raise ValueError(f"Invalid boolean value for {field}: {value!r}")
        return bool(value)
    return value


def make_index_action(
    index: str,
    row: dict[str, Any],
    vector: np.ndarray,
) -> dict[str, Any]:
    """Convert one payload row and vector into an Elasticsearch bulk action."""
    chunk_id = _normalize_value(row.get("chunk_id"))
    if not chunk_id:
        raise ValueError("Missing chunk_id")

    normalized_vector = np.asarray(vector, dtype=np.float32)
    if normalized_vector.ndim != 1 or normalized_vector.shape[0] != VECTOR_SIZE:
        raise ValueError(
            f"Bad vector shape for chunk_id={chunk_id}: {normalized_vector.shape}"
        )
    if not np.isfinite(normalized_vector).all():
        raise ValueError(f"Vector contains NaN/Inf for chunk_id={chunk_id}")

    source: dict[str, Any] = {}
    for field in PAYLOAD_FIELDS:
        value = _normalize_payload_field(field, row.get(field))
        if value is not None:
            source[field] = value
    source["chunk_id"] = str(chunk_id)
    source["vector"] = normalized_vector.tolist()
    return {
        "_index": index,
        "_id": stable_point_id(str(chunk_id)),
        "_source": source,
    }


def build_elasticsearch_filter(
    filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Translate the common dense retrieval filter contract to Elasticsearch."""
    if not filters:
        return []
    clauses: list[dict[str, Any]] = []
    ranges = filters.get("ranges", {})
    for field, expected in filters.items():
        if field == "ranges":
            continue
        target_field = f"{field}.keyword" if field in TEXT_FIELDS else field
        if field == "doc_id":
            expected = (
                [str(value) for value in expected]
                if isinstance(expected, list)
                else str(expected)
            )
        if isinstance(expected, list):
            clauses.append({"terms": {target_field: expected}})
        else:
            clauses.append({"term": {target_field: expected}})
    for field, bounds in ranges.items():
        clauses.append({"range": {field: bounds}})
    return clauses


def normalize_search_hits(
    hits: list[dict[str, Any]],
    *,
    cosine_score: bool = False,
) -> list[tuple[float, dict[str, Any]]]:
    """Normalize Elasticsearch hits to the retriever's score/payload contract."""
    normalized: list[tuple[float, dict[str, Any]]] = []
    for hit in hits:
        payload = dict(hit.get("_source") or {})
        payload.pop("vector", None)
        score = float(hit.get("_score") or 0.0)
        if cosine_score:
            score = 2.0 * score - 1.0
        normalized.append((score, payload))
    return normalized


def resolve_num_candidates(top_k: int, configured: int | None) -> int:
    """Choose an Elasticsearch kNN candidate count within API limits."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if configured is not None and configured <= 0:
        raise ValueError("elastic_num_candidates must be positive")
    requested = configured if configured is not None else max(100, top_k * 20)
    return min(10_000, max(top_k, requested))
