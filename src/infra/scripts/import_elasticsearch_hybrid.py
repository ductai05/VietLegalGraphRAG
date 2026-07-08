"""Import sparse text first, then update dense vectors into one ES index.

Run from the repository root or from this directory. The script expects the
pipeline branch/artifacts to have produced:

* data/retrieval/sparse/bm25_v0.1/sparse_payload.parquet
* data/retrieval/dense/vnlegal_lal_v0.1/manifest.json
* data/retrieval/dense/vnlegal_lal_v0.1/payload/*.parquet
* data/retrieval/dense/vnlegal_lal_v0.1/vectors/*.npy
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPARSE_PAYLOAD = (
    REPO_ROOT / "data/retrieval/sparse/bm25_v0.1/sparse_payload.parquet"
)
DEFAULT_DENSE_DIR = REPO_ROOT / "data/retrieval/dense/vnlegal_lal_v0.1"
DEFAULT_CHECKPOINT = (
    REPO_ROOT / "data/retrieval/elasticsearch_hybrid_ingest_checkpoint.json"
)
DEFAULT_INDEX = "vietlegal_chunks_hybrid_v1"
DEFAULT_ALIAS = "vietlegal_chunks"
DEFAULT_VECTOR_DIMS = 1024

TEXT_FIELDS = {
    "chunk_text",
    "contextual_text",
    "section_path",
    "procedure_name",
    "title",
    "issuing_authority",
}
VI_TEXT_FIELDS = {
    "chunk_text_vi",
    "contextual_text_vi",
    "title_vi",
    "section_path_vi",
    "procedure_name_vi",
    "issuing_authority_vi",
    "chunk_text_folded",
    "title_folded",
    "section_path_folded",
    "procedure_name_folded",
    "issuing_authority_folded",
}
BOOLEAN_FIELDS = {
    "embed",
    "keyword_index",
    "do_not_answer_from_summary",
}
INTEGER_FIELDS = {
    "token_estimate",
    "char_count",
    "issuance_date_ts",
    "effect_date_ts",
    "effectless_date_ts",
}
DATE_FIELDS = {
    "issuance_date",
    "effect_date",
    "effectless_date",
}
KEYWORD_FIELDS = {
    "chunk_id",
    "doc_id",
    "source",
    "chunk_type",
    "parent_id",
    "prev_chunk_id",
    "next_chunk_id",
    "table_id",
    "raw_table_id",
    "summary_of",
    "answer_source",
    "quality_flags",
    "table_columns",
    "document_number",
    "document_number_norm",
    "legal_type",
    "legal_sectors",
    "effect_status",
    "linh_vuc",
    "nganh",
    "pham_vi",
    "expansion_status",
    "ingest_truncated_fields",
}
SOURCE_FIELDS = (
    sorted(KEYWORD_FIELDS)
    + sorted(TEXT_FIELDS)
    + sorted(VI_TEXT_FIELDS)
    + sorted(BOOLEAN_FIELDS)
    + sorted(INTEGER_FIELDS)
    + sorted(DATE_FIELDS)
)


@dataclass(frozen=True)
class BulkResult:
    ok: int
    failed: int
    elapsed_seconds: float

    @property
    def rows_per_second(self) -> float:
        return self.ok / max(self.elapsed_seconds, 1e-9)


@dataclass
class DenseDedupeTracker:
    """Track dense chunk ids so duplicate vectors do not update the same doc twice."""

    seen_chunk_ids: set[str] = field(default_factory=set)
    duplicates_skipped: int = 0

    def should_update(self, chunk_id: str) -> bool:
        if chunk_id in self.seen_chunk_ids:
            self.duplicates_skipped += 1
            return False
        self.seen_chunk_ids.add(chunk_id)
        return True


def keyword_mapping(ignore_above: int = 8192) -> dict[str, Any]:
    return {"type": "keyword", "ignore_above": ignore_above}


def standard_text_mapping(keyword_ignore_above: int = 2048) -> dict[str, Any]:
    return {
        "type": "text",
        "analyzer": "standard",
        "fields": {"keyword": keyword_mapping(keyword_ignore_above)},
    }


def vi_text_mapping() -> dict[str, Any]:
    return {"type": "text", "analyzer": "vi_whitespace"}


def build_hybrid_index_definition(
    *,
    vector_dims: int = DEFAULT_VECTOR_DIMS,
    number_of_shards: int = 1,
    number_of_replicas: int = 0,
) -> dict[str, Any]:
    """Return one mapping that supports BM25, metadata filters, and kNN."""
    if vector_dims <= 0:
        raise ValueError("vector_dims must be positive")
    if number_of_shards <= 0:
        raise ValueError("number_of_shards must be positive")
    if number_of_replicas < 0:
        raise ValueError("number_of_replicas cannot be negative")

    properties: dict[str, Any] = {
        field: keyword_mapping() for field in sorted(KEYWORD_FIELDS)
    }
    properties["document_number_norm"] = {
        "type": "keyword",
        "normalizer": "lowercase_norm",
        "ignore_above": 8192,
    }
    for field in TEXT_FIELDS:
        properties[field] = standard_text_mapping()
    for field in VI_TEXT_FIELDS:
        properties[field] = vi_text_mapping()
    for field in BOOLEAN_FIELDS:
        properties[field] = {"type": "boolean"}
    for field in INTEGER_FIELDS:
        properties[field] = {"type": "integer"}
    for field in DATE_FIELDS:
        properties[field] = {"type": "date", "ignore_malformed": True}
    properties["vector"] = {
        "type": "dense_vector",
        "dims": vector_dims,
        "index": True,
        "similarity": "cosine",
    }

    return {
        "settings": {
            "index": {
                "number_of_shards": number_of_shards,
                "number_of_replicas": number_of_replicas,
                "refresh_interval": "-1",
            },
            "analysis": {
                "analyzer": {
                    "vi_whitespace": {
                        "type": "custom",
                        "tokenizer": "whitespace",
                        "filter": ["lowercase"],
                    }
                },
                "normalizer": {
                    "lowercase_norm": {
                        "type": "custom",
                        "filter": ["lowercase"],
                    }
                },
            },
        },
        "mappings": {
            "dynamic": False,
            "properties": properties,
        },
    }


def json_ready(value: Any) -> Any:
    """Convert numpy, Arrow, pandas, and date values into JSON-safe values."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return json_ready(value.item())
    if isinstance(value, np.ndarray):
        return json_ready(value.tolist())
    if hasattr(value, "as_py"):
        try:
            return json_ready(value.as_py())
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return json_ready(value.item())
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return json_ready(value.tolist())
        except Exception:
            pass
    if isinstance(value, (list, tuple, set)):
        normalized = [json_ready(item) for item in value]
        return [item for item in normalized if item is not None]
    if isinstance(value, dict):
        return {
            str(key): normalized
            for key, item in value.items()
            if (normalized := json_ready(item)) is not None
        }
    return value


def _coerce_bool(field: str, value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
        raise ValueError(f"Invalid boolean for {field}: {value!r}")
    return bool(value)


def _normalize_sparse_source(
    row: dict[str, Any],
    *,
    max_text_chars: int | None,
) -> dict[str, Any]:
    source: dict[str, Any] = {}
    truncated_fields: list[str] = []
    for field in SOURCE_FIELDS:
        value = json_ready(row.get(field))
        if value is None:
            continue
        if field in BOOLEAN_FIELDS:
            value = _coerce_bool(field, value)
        elif field in INTEGER_FIELDS:
            value = int(value)
        elif (
            max_text_chars is not None
            and max_text_chars > 0
            and field in TEXT_FIELDS | VI_TEXT_FIELDS
            and isinstance(value, str)
            and len(value) > max_text_chars
        ):
            value = value[:max_text_chars]
            truncated_fields.append(field)
        source[field] = value
    if truncated_fields:
        source["ingest_truncated_fields"] = truncated_fields
    return source


def _require_chunk_id(row: dict[str, Any]) -> str:
    chunk_id = json_ready(row.get("chunk_id"))
    if not chunk_id:
        raise ValueError("Missing chunk_id")
    return str(chunk_id)


def make_sparse_index_action(
    index: str,
    row: dict[str, Any],
    *,
    max_text_chars: int | None = 200_000,
) -> dict[str, Any]:
    """Build the phase-1 sparse/text index action."""
    chunk_id = _require_chunk_id(row)
    source = _normalize_sparse_source(row, max_text_chars=max_text_chars)
    source["chunk_id"] = chunk_id
    return {
        "_op_type": "index",
        "_index": index,
        "_id": chunk_id,
        "_source": source,
    }


def make_dense_update_action(
    index: str,
    row: dict[str, Any],
    vector: np.ndarray,
    *,
    vector_dims: int = DEFAULT_VECTOR_DIMS,
) -> dict[str, Any]:
    """Build the phase-2 dense vector update action for an existing chunk."""
    chunk_id = _require_chunk_id(row)
    normalized_vector = np.asarray(vector, dtype=np.float32)
    if normalized_vector.ndim != 1 or normalized_vector.shape[0] != vector_dims:
        raise ValueError(
            f"Bad vector shape for chunk_id={chunk_id}: {normalized_vector.shape}"
        )
    if not np.isfinite(normalized_vector).all():
        raise ValueError(f"Vector contains NaN/Inf for chunk_id={chunk_id}")
    return {
        "_op_type": "update",
        "_index": index,
        "_id": chunk_id,
        "doc": {"vector": normalized_vector.tolist()},
        "doc_as_upsert": False,
    }


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else dict(default)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def append_dead_letter(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(json_ready(record), ensure_ascii=False) + "\n")


def iter_sparse_actions(
    rows: Iterable[dict[str, Any]],
    *,
    index: str,
    max_text_chars: int | None,
    dead_letter_path: Path | None = None,
) -> Iterator[dict[str, Any]]:
    for ordinal, row in enumerate(rows):
        try:
            yield make_sparse_index_action(
                index,
                row,
                max_text_chars=max_text_chars,
            )
        except Exception as exc:
            if dead_letter_path is not None:
                append_dead_letter(
                    dead_letter_path,
                    {
                        "phase": "sparse_action",
                        "ordinal": ordinal,
                        "chunk_id": row.get("chunk_id"),
                        "error": str(exc),
                    },
                )
            else:
                raise


def iter_dense_update_actions(
    rows: Sequence[dict[str, Any]],
    vectors: np.ndarray,
    *,
    index: str,
    vector_dims: int,
    dead_letter_path: Path | None = None,
) -> Iterator[dict[str, Any]]:
    if len(rows) != len(vectors):
        raise ValueError(
            f"Payload/vector row mismatch: payload rows={len(rows)}, "
            f"vector rows={len(vectors)}"
        )
    for ordinal, row in enumerate(rows):
        try:
            yield make_dense_update_action(
                index,
                row,
                vectors[ordinal],
                vector_dims=vector_dims,
            )
        except Exception as exc:
            if dead_letter_path is not None:
                append_dead_letter(
                    dead_letter_path,
                    {
                        "phase": "dense_action",
                        "ordinal": ordinal,
                        "chunk_id": row.get("chunk_id"),
                        "error": str(exc),
                    },
                )
            else:
                raise


def build_sparse_action_batch(
    rows: Sequence[dict[str, Any]],
    *,
    index: str,
    max_text_chars: int | None,
    dead_letter_path: Path,
    base_ordinal: int,
) -> tuple[list[dict[str, Any]], int]:
    actions: list[dict[str, Any]] = []
    failed = 0
    for offset, row in enumerate(rows):
        try:
            actions.append(
                make_sparse_index_action(
                    index,
                    row,
                    max_text_chars=max_text_chars,
                )
            )
        except Exception as exc:
            failed += 1
            append_dead_letter(
                dead_letter_path,
                {
                    "phase": "sparse_action",
                    "ordinal": base_ordinal + offset,
                    "chunk_id": row.get("chunk_id"),
                    "error": str(exc),
                },
            )
    return actions, failed


def build_dense_action_batch(
    rows: Sequence[dict[str, Any]],
    vectors: np.ndarray,
    *,
    index: str,
    vector_dims: int,
    dead_letter_path: Path,
    base_ordinal: int,
    dedupe_tracker: DenseDedupeTracker | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if len(rows) != len(vectors):
        raise ValueError(
            f"Payload/vector row mismatch: payload rows={len(rows)}, "
            f"vector rows={len(vectors)}"
        )
    actions: list[dict[str, Any]] = []
    failed = 0
    for offset, row in enumerate(rows):
        try:
            chunk_id = _require_chunk_id(row)
            if dedupe_tracker is not None and not dedupe_tracker.should_update(chunk_id):
                continue
            actions.append(
                make_dense_update_action(
                    index,
                    row,
                    vectors[offset],
                    vector_dims=vector_dims,
                )
            )
        except Exception as exc:
            failed += 1
            append_dead_letter(
                dead_letter_path,
                {
                    "phase": "dense_action",
                    "ordinal": base_ordinal + offset,
                    "chunk_id": row.get("chunk_id"),
                    "error": str(exc),
                },
            )
    return actions, failed


def summarize_bulk_error(error_info: Any) -> dict[str, Any]:
    if not isinstance(error_info, dict):
        return {"reason": str(error_info)}
    operation = next(
        (name for name in ("index", "create", "update", "delete") if name in error_info),
        None,
    )
    if operation is None:
        return {"raw_error_keys": sorted(error_info)}
    item = error_info.get(operation) or {}
    error = item.get("error") or {}
    caused_by = error.get("caused_by") if isinstance(error, dict) else None
    return {
        "op": operation,
        "status": item.get("status"),
        "_index": item.get("_index"),
        "_id": item.get("_id"),
        "error_type": error.get("type") if isinstance(error, dict) else None,
        "reason": error.get("reason") if isinstance(error, dict) else str(error),
        "caused_by_type": caused_by.get("type") if isinstance(caused_by, dict) else None,
        "caused_by_reason": (
            caused_by.get("reason") if isinstance(caused_by, dict) else None
        ),
    }


def bulk_actions(
    *,
    client: Any,
    actions: Iterable[dict[str, Any]],
    batch_size: int,
    max_chunk_bytes: int,
    max_retries: int,
    initial_backoff: float,
    max_backoff: float,
    request_timeout: int,
    dead_letter_path: Path,
    phase: str,
    bulk_fn: Callable[..., tuple[int, list[Any]]] | None = None,
) -> BulkResult:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_chunk_bytes <= 0:
        raise ValueError("max_chunk_bytes must be positive")
    if max_retries < 0:
        raise ValueError("max_retries cannot be negative")
    if initial_backoff <= 0:
        raise ValueError("initial_backoff must be positive")
    if max_backoff <= 0:
        raise ValueError("max_backoff must be positive")
    if isinstance(actions, Sequence) and len(actions) == 0:
        return BulkResult(ok=0, failed=0, elapsed_seconds=1e-9)

    bulk = bulk_fn
    if bulk is None:
        try:
            from elasticsearch import helpers
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "Elasticsearch import requires `elasticsearch`. "
                "Install root requirements before running this script."
            ) from exc
        bulk = helpers.bulk

    bulk_client = (
        client.options(request_timeout=request_timeout)
        if hasattr(client, "options")
        else client
    )
    started = time.perf_counter()
    ok, errors = bulk(
        bulk_client,
        actions,
        chunk_size=batch_size,
        max_chunk_bytes=max_chunk_bytes,
        max_retries=max_retries,
        initial_backoff=initial_backoff,
        max_backoff=max_backoff,
        retry_on_status=(429, 502, 503, 504),
        raise_on_error=False,
    )
    for error in errors:
        append_dead_letter(
            dead_letter_path,
            {
                "phase": phase,
                "error": summarize_bulk_error(error),
            },
        )
    return BulkResult(
        ok=int(ok),
        failed=len(errors),
        elapsed_seconds=max(time.perf_counter() - started, 1e-9),
    )


def enforce_error_budget(
    *,
    failed_total: int,
    processed_total: int,
    max_errors: int,
    max_error_rate: float,
    phase: str,
) -> None:
    if max_errors < 0:
        raise ValueError("max_errors cannot be negative")
    if max_error_rate < 0:
        raise ValueError("max_error_rate cannot be negative")
    rate = failed_total / max(processed_total, 1)
    if failed_total > max_errors or rate > max_error_rate:
        raise RuntimeError(
            f"{phase} exceeded error budget: failed={failed_total:,}, "
            f"processed={processed_total:,}, rate={rate:.4%}"
        )


def load_env_file(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


def build_elasticsearch_client(
    *,
    url: str,
    api_key: str | None,
    username: str | None,
    password: str | None,
    verify_certs: bool,
    request_timeout: int,
) -> Any:
    try:
        from elasticsearch import Elasticsearch
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Elasticsearch import requires `elasticsearch`. "
            "Install root requirements before running this script."
        ) from exc

    for key in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
    ):
        os.environ.pop(key, None)
    kwargs: dict[str, Any] = {
        "request_timeout": request_timeout,
        "verify_certs": verify_certs,
        "retry_on_timeout": True,
        "max_retries": 5,
    }
    if api_key:
        kwargs["api_key"] = api_key
    elif username and password:
        kwargs["basic_auth"] = (username, password)
    return Elasticsearch(url, **kwargs)


def _is_serverless_unavailable_settings_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "serverless" in message
        and "number_of_shards" in message
        and "number_of_replicas" in message
    )


def _serverless_create_body(body: dict[str, Any]) -> dict[str, Any]:
    serverless_body = json.loads(json.dumps(body))
    index_settings = serverless_body.get("settings", {}).get("index", {})
    index_settings.pop("number_of_shards", None)
    index_settings.pop("number_of_replicas", None)
    return serverless_body


def ensure_index(
    client: Any,
    *,
    index: str,
    recreate: bool,
    vector_dims: int,
    number_of_shards: int,
) -> None:
    exists = bool(client.indices.exists(index=index))
    if exists and recreate:
        logging.info("Deleting existing index %s", index)
        client.indices.delete(index=index)
        exists = False
    if exists:
        mapping = client.indices.get_mapping(index=index)
        properties = mapping[index]["mappings"].get("properties", {})
        vector = properties.get("vector", {})
        if vector.get("type") != "dense_vector" or vector.get("dims") != vector_dims:
            raise ValueError(
                f"Existing index {index!r} has incompatible vector mapping"
            )
        logging.info("Using existing compatible index %s", index)
        return

    body = build_hybrid_index_definition(
        vector_dims=vector_dims,
        number_of_shards=number_of_shards,
        number_of_replicas=0,
    )
    try:
        client.indices.create(index=index, body=body)
    except Exception as exc:
        if not _is_serverless_unavailable_settings_error(exc):
            raise
        logging.info(
            "Retrying index creation without shard/replica settings for Elasticsearch serverless"
        )
        client.indices.create(index=index, body=_serverless_create_body(body))
    logging.info("Created index %s", index)


def update_alias(client: Any, *, index: str, alias: str) -> None:
    actions: list[dict[str, Any]] = []
    if client.indices.exists_alias(name=alias):
        current = client.indices.get_alias(name=alias)
        for current_index in current.keys():
            actions.append({"remove": {"index": current_index, "alias": alias}})
    actions.append({"add": {"index": index, "alias": alias}})
    client.indices.update_aliases(actions=actions)


def finalize_index(
    client: Any,
    *,
    index: str,
    alias: str,
    final_refresh_interval: str,
    final_replicas: int,
) -> None:
    try:
        client.indices.put_settings(
            index=index,
            settings={
                "index": {
                    "refresh_interval": final_refresh_interval,
                    "number_of_replicas": final_replicas,
                }
            },
        )
    except Exception as exc:
        if "serverless" not in str(exc).lower():
            raise
        client.indices.put_settings(
            index=index,
            settings={"index": {"refresh_interval": final_refresh_interval}},
        )
    client.indices.refresh(index=index)
    update_alias(client, index=index, alias=alias)


def _checkpoint_identity(
    *,
    index: str,
    sparse_payload: Path,
    dense_dir: Path,
    vector_dims: int,
) -> dict[str, Any]:
    return {
        "index": index,
        "sparse_payload": str(sparse_payload.resolve()),
        "dense_dir": str(dense_dir.resolve()),
        "vector_dims": vector_dims,
    }


def prepare_checkpoint(
    *,
    checkpoint_path: Path,
    recreate: bool,
    index: str,
    sparse_payload: Path,
    dense_dir: Path,
    vector_dims: int,
) -> dict[str, Any]:
    identity = _checkpoint_identity(
        index=index,
        sparse_payload=sparse_payload,
        dense_dir=dense_dir,
        vector_dims=vector_dims,
    )
    checkpoint = {} if recreate else read_json(checkpoint_path, {})
    existing_identity = checkpoint.get("identity")
    if existing_identity not in (None, identity):
        raise ValueError(
            "Checkpoint belongs to another ingest input or index. "
            "Use --recreate or a different --checkpoint."
        )
    checkpoint["identity"] = identity
    checkpoint.setdefault("sparse", {"processed": 0, "indexed": 0, "failed": 0})
    checkpoint.setdefault("dense", {"indexed": 0, "failed": 0, "shards": {}})
    checkpoint.setdefault("finalized", False)
    return checkpoint


def ingest_sparse_payload(
    *,
    client: Any,
    index: str,
    payload_path: Path,
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
    dead_letter_path: Path,
    batch_size: int,
    max_chunk_bytes: int,
    max_retries: int,
    initial_backoff: float,
    max_backoff: float,
    request_timeout: int,
    max_text_chars: int | None,
    max_errors: int,
    max_error_rate: float,
    max_rows: int | None,
) -> None:
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Sparse ingest requires `pyarrow`. Install root requirements first."
        ) from exc

    parquet_file = pq.ParquetFile(payload_path)
    total_rows = parquet_file.metadata.num_rows
    selected_total = min(total_rows, max_rows) if max_rows is not None else total_rows
    sparse_state = checkpoint.setdefault(
        "sparse",
        {"processed": 0, "indexed": 0, "failed": 0},
    )
    processed = int(sparse_state.get("processed", 0))
    indexed = int(sparse_state.get("indexed", 0))
    failed = int(sparse_state.get("failed", 0))
    seen = 0

    if processed >= selected_total:
        logging.info("Sparse phase already checkpointed: %s/%s rows", processed, selected_total)
        return

    for record_batch in parquet_file.iter_batches(batch_size=batch_size):
        rows = record_batch.to_pylist()
        batch_start = seen
        batch_end = seen + len(rows)
        seen = batch_end
        if batch_start >= selected_total:
            break
        if batch_end <= processed:
            continue
        if processed > batch_start:
            rows = rows[processed - batch_start :]
            batch_start = processed
        if batch_start + len(rows) > selected_total:
            rows = rows[: selected_total - batch_start]

        actions, action_failed = build_sparse_action_batch(
            rows,
            index=index,
            max_text_chars=max_text_chars,
            dead_letter_path=dead_letter_path,
            base_ordinal=batch_start,
        )
        result = bulk_actions(
            client=client,
            actions=actions,
            batch_size=batch_size,
            max_chunk_bytes=max_chunk_bytes,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            max_backoff=max_backoff,
            request_timeout=request_timeout,
            dead_letter_path=dead_letter_path,
            phase="sparse_bulk",
        )
        processed += len(rows)
        indexed += result.ok
        failed += action_failed + result.failed
        sparse_state.update(
            {
                "processed": processed,
                "indexed": indexed,
                "failed": failed,
                "total_rows": selected_total,
            }
        )
        atomic_write_json(checkpoint_path, checkpoint)
        enforce_error_budget(
            failed_total=failed,
            processed_total=processed,
            max_errors=max_errors,
            max_error_rate=max_error_rate,
            phase="sparse",
        )
        logging.info(
            "Sparse phase: indexed=%s processed=%s/%s failed=%s rate=%.1f rows/s",
            f"{indexed:,}",
            f"{processed:,}",
            f"{selected_total:,}",
            f"{failed:,}",
            result.rows_per_second,
        )


def _read_dense_payload_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Dense ingest requires `pyarrow`. Install root requirements first."
        ) from exc
    return pq.read_table(path, columns=["chunk_id"]).to_pylist()


def resolve_dense_shard_path(
    dense_dir: Path,
    manifest_path_value: str,
    *,
    artifact_subdir: str,
) -> Path:
    candidate = Path(manifest_path_value)
    if candidate.is_absolute():
        return candidate

    direct = dense_dir / candidate
    if direct.exists():
        return direct

    nested = dense_dir / artifact_subdir / candidate
    if nested.exists():
        return nested

    return direct


def _completed_dense_shards(
    manifest: dict[str, Any],
    *,
    max_dense_shards: int | None,
) -> list[tuple[str, dict[str, Any]]]:
    shards = [
        (key, value)
        for key, value in sorted((manifest.get("shards") or {}).items())
        if value.get("status") == "done"
    ]
    if max_dense_shards is not None:
        shards = shards[:max_dense_shards]
    return shards


def ingest_dense_vectors(
    *,
    client: Any,
    index: str,
    dense_dir: Path,
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
    dead_letter_path: Path,
    batch_size: int,
    max_chunk_bytes: int,
    max_retries: int,
    initial_backoff: float,
    max_backoff: float,
    request_timeout: int,
    vector_dims: int,
    max_errors: int,
    max_error_rate: float,
    max_dense_shards: int | None,
) -> None:
    manifest_path = dense_dir / "manifest.json"
    manifest = read_json(manifest_path)
    shards = _completed_dense_shards(manifest, max_dense_shards=max_dense_shards)
    if not shards:
        raise ValueError(f"No completed dense shards in {manifest_path}")

    dense_state = checkpoint.setdefault(
        "dense",
        {"indexed": 0, "failed": 0, "shards": {}},
    )
    shard_state = dense_state.setdefault("shards", {})
    processed_rows = sum(int(item.get("processed", 0)) for item in shard_state.values())
    indexed = int(dense_state.get("indexed", 0))
    failed = int(dense_state.get("failed", 0))
    duplicates_skipped = sum(
        int(item.get("duplicates_skipped", 0)) for item in shard_state.values()
    )
    selected_rows = sum(int(info["rows"]) for _, info in shards)
    dedupe_tracker = DenseDedupeTracker()
    primed_rows = 0

    for shard_key, shard_info in shards:
        previous = shard_state.get(shard_key, {})
        if (
            previous.get("status") == "done"
            and previous.get("rows") == shard_info.get("rows")
        ):
            payload_path = resolve_dense_shard_path(
                dense_dir,
                shard_info["payload"],
                artifact_subdir="payload",
            )
            for row in _read_dense_payload_rows(payload_path):
                dedupe_tracker.seen_chunk_ids.add(_require_chunk_id(row))
                primed_rows += 1
    if primed_rows:
        logging.info(
            "Dense phase: primed dedupe tracker with %s chunk ids from checkpointed shards",
            f"{primed_rows:,}",
        )

    for ordinal, (shard_key, shard_info) in enumerate(shards, start=1):
        previous = shard_state.get(shard_key, {})
        if (
            previous.get("status") == "done"
            and previous.get("rows") == shard_info.get("rows")
        ):
            logging.info(
                "Dense phase: skipping shard %s (%s/%s)",
                shard_key,
                ordinal,
                len(shards),
            )
            continue

        payload_path = resolve_dense_shard_path(
            dense_dir,
            shard_info["payload"],
            artifact_subdir="payload",
        )
        vector_path = resolve_dense_shard_path(
            dense_dir,
            shard_info["vectors"],
            artifact_subdir="vectors",
        )
        rows = _read_dense_payload_rows(payload_path)
        vectors = np.load(vector_path, mmap_mode="r")
        if len(rows) != len(vectors):
            raise ValueError(
                f"Payload/vector row mismatch for shard {shard_key}: "
                f"payload rows={len(rows)}, vector rows={len(vectors)}"
            )
        shard_indexed = 0
        shard_failed = 0
        shard_duplicates_start = dedupe_tracker.duplicates_skipped
        shard_started = time.perf_counter()
        for start in range(0, len(rows), batch_size):
            stop = min(start + batch_size, len(rows))
            action_batch, action_failed = build_dense_action_batch(
                rows[start:stop],
                vectors[start:stop],
                index=index,
                vector_dims=vector_dims,
                dead_letter_path=dead_letter_path,
                base_ordinal=start,
                dedupe_tracker=dedupe_tracker,
            )
            result = bulk_actions(
                client=client,
                actions=action_batch,
                batch_size=batch_size,
                max_chunk_bytes=max_chunk_bytes,
                max_retries=max_retries,
                initial_backoff=initial_backoff,
                max_backoff=max_backoff,
                request_timeout=request_timeout,
                dead_letter_path=dead_letter_path,
                phase="dense_bulk",
            )
            shard_indexed += result.ok
            shard_failed += action_failed + result.failed
        processed_rows += int(shard_info["rows"])
        indexed += shard_indexed
        failed += shard_failed
        shard_duplicates = dedupe_tracker.duplicates_skipped - shard_duplicates_start
        duplicates_skipped += shard_duplicates
        shard_state[shard_key] = {
            "status": "done",
            "rows": int(shard_info["rows"]),
            "indexed": shard_indexed,
            "failed": shard_failed,
            "duplicates_skipped": shard_duplicates,
        }
        dense_state.update(
            {
                "indexed": indexed,
                "failed": failed,
                "processed": processed_rows,
                "total_rows": selected_rows,
                "duplicates_skipped": duplicates_skipped,
            }
        )
        atomic_write_json(checkpoint_path, checkpoint)
        enforce_error_budget(
            failed_total=failed,
            processed_total=max(processed_rows, 1),
            max_errors=max_errors,
            max_error_rate=max_error_rate,
            phase="dense",
        )
        logging.info(
            "Dense phase: shard=%s indexed=%s duplicates=%s processed=%s/%s failed=%s rate=%.1f rows/s",
            shard_key,
            f"{shard_indexed:,}",
            f"{shard_duplicates:,}",
            f"{processed_rows:,}",
            f"{selected_rows:,}",
            f"{failed:,}",
            shard_indexed / max(time.perf_counter() - shard_started, 1e-9),
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--env-file", type=Path, default=None)
    pre_args, _ = pre_parser.parse_known_args(argv)
    load_env_file(pre_args.env_file)
    load_env_file(REPO_ROOT / "src/infra/.env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=pre_args.env_file)
    parser.add_argument("--url", default=os.getenv("ELASTICSEARCH_URL") or os.getenv("ELASTIC_URL"))
    parser.add_argument("--api-key", default=os.getenv("ELASTICSEARCH_API_KEY") or os.getenv("ELASTIC_API_KEY"))
    parser.add_argument("--username", default=os.getenv("ELASTICSEARCH_USERNAME") or os.getenv("ELASTIC_USERNAME"))
    parser.add_argument("--password", default=os.getenv("ELASTICSEARCH_PASSWORD") or os.getenv("ELASTIC_PASSWORD"))
    parser.add_argument("--index", default=os.getenv("ELASTICSEARCH_INDEX", DEFAULT_INDEX))
    parser.add_argument("--alias", default=os.getenv("ELASTICSEARCH_ALIAS", DEFAULT_ALIAS))
    parser.add_argument("--sparse-payload", type=Path, default=DEFAULT_SPARSE_PAYLOAD)
    parser.add_argument("--dense-dir", type=Path, default=DEFAULT_DENSE_DIR)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--dead-letter", type=Path, default=None)
    parser.add_argument("--sparse-batch-size", type=int, default=1000)
    parser.add_argument("--dense-batch-size", type=int, default=200)
    parser.add_argument(
        "--sparse-max-chunk-mb",
        type=float,
        default=float(os.getenv("ELASTICSEARCH_SPARSE_MAX_CHUNK_MB", "8")),
        help="Max serialized bulk request size for sparse indexing.",
    )
    parser.add_argument(
        "--dense-max-chunk-mb",
        type=float,
        default=float(os.getenv("ELASTICSEARCH_DENSE_MAX_CHUNK_MB", "8")),
        help="Max serialized bulk request size for dense vector updates.",
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--retry-initial-backoff",
        type=float,
        default=float(os.getenv("ELASTICSEARCH_RETRY_INITIAL_BACKOFF", "1")),
    )
    parser.add_argument(
        "--retry-max-backoff",
        type=float,
        default=float(os.getenv("ELASTICSEARCH_RETRY_MAX_BACKOFF", "60")),
    )
    parser.add_argument("--request-timeout", type=int, default=300)
    parser.add_argument("--vector-dims", type=int, default=DEFAULT_VECTOR_DIMS)
    parser.add_argument("--number-of-shards", type=int, default=1)
    parser.add_argument("--final-replicas", type=int, default=0)
    parser.add_argument("--final-refresh-interval", default="5s")
    parser.add_argument("--max-text-chars", type=int, default=200_000)
    parser.add_argument("--max-errors", type=int, default=100_000)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-sparse-rows", type=int, default=None)
    parser.add_argument("--max-dense-shards", type=int, default=None)
    parser.add_argument("--skip-sparse", action="store_true")
    parser.add_argument("--skip-dense", action="store_true")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--no-verify-certs", action="store_true")
    parser.add_argument("--log-file", type=Path, default=None)
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    positive = {
        "--sparse-batch-size": args.sparse_batch_size,
        "--dense-batch-size": args.dense_batch_size,
        "--sparse-max-chunk-mb": args.sparse_max_chunk_mb,
        "--dense-max-chunk-mb": args.dense_max_chunk_mb,
        "--retry-initial-backoff": args.retry_initial_backoff,
        "--retry-max-backoff": args.retry_max_backoff,
        "--request-timeout": args.request_timeout,
        "--vector-dims": args.vector_dims,
        "--number-of-shards": args.number_of_shards,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if args.final_replicas < 0:
        raise ValueError("--final-replicas cannot be negative")
    if args.max_retries < 0:
        raise ValueError("--max-retries cannot be negative")
    if args.retry_max_backoff < args.retry_initial_backoff:
        raise ValueError("--retry-max-backoff must be >= --retry-initial-backoff")
    if args.max_errors < 0:
        raise ValueError("--max-errors cannot be negative")
    if args.max_error_rate < 0:
        raise ValueError("--max-error-rate cannot be negative")
    if args.max_sparse_rows is not None and args.max_sparse_rows <= 0:
        raise ValueError("--max-sparse-rows must be positive")
    if args.max_dense_shards is not None and args.max_dense_shards <= 0:
        raise ValueError("--max-dense-shards must be positive")
    if args.skip_sparse and args.skip_dense:
        raise ValueError("At least one phase must run")
    if not args.url:
        raise ValueError("Missing Elasticsearch URL. Set ELASTICSEARCH_URL or pass --url.")
    if not args.api_key and not (args.username and args.password):
        raise ValueError(
            "Missing Elasticsearch credentials. Set ELASTICSEARCH_API_KEY "
            "or ELASTICSEARCH_USERNAME/ELASTICSEARCH_PASSWORD."
        )
    if not args.skip_sparse and not args.sparse_payload.exists():
        raise FileNotFoundError(f"Sparse payload not found: {args.sparse_payload}")
    if not args.skip_dense and not (args.dense_dir / "manifest.json").exists():
        raise FileNotFoundError(f"Dense manifest not found: {args.dense_dir / 'manifest.json'}")


def setup_logging(log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    validate_args(args)
    setup_logging(args.log_file)

    dead_letter_path = (
        args.dead_letter
        if args.dead_letter is not None
        else args.checkpoint.with_suffix(".deadletter.jsonl")
    )
    checkpoint = prepare_checkpoint(
        checkpoint_path=args.checkpoint,
        recreate=args.recreate,
        index=args.index,
        sparse_payload=args.sparse_payload,
        dense_dir=args.dense_dir,
        vector_dims=args.vector_dims,
    )

    client = build_elasticsearch_client(
        url=args.url,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        verify_certs=not args.no_verify_certs,
        request_timeout=args.request_timeout,
    )
    try:
        info = client.info()
        logging.info("Connected to Elasticsearch cluster %s", info.get("cluster_name"))
        ensure_index(
            client,
            index=args.index,
            recreate=args.recreate,
            vector_dims=args.vector_dims,
            number_of_shards=args.number_of_shards,
        )
        atomic_write_json(args.checkpoint, checkpoint)

        if not args.skip_sparse:
            ingest_sparse_payload(
                client=client,
                index=args.index,
                payload_path=args.sparse_payload,
                checkpoint=checkpoint,
                checkpoint_path=args.checkpoint,
                dead_letter_path=dead_letter_path,
                batch_size=args.sparse_batch_size,
                max_chunk_bytes=int(args.sparse_max_chunk_mb * 1024 * 1024),
                max_retries=args.max_retries,
                initial_backoff=args.retry_initial_backoff,
                max_backoff=args.retry_max_backoff,
                request_timeout=args.request_timeout,
                max_text_chars=args.max_text_chars,
                max_errors=args.max_errors,
                max_error_rate=args.max_error_rate,
                max_rows=args.max_sparse_rows,
            )
        if not args.skip_dense:
            ingest_dense_vectors(
                client=client,
                index=args.index,
                dense_dir=args.dense_dir,
                checkpoint=checkpoint,
                checkpoint_path=args.checkpoint,
                dead_letter_path=dead_letter_path,
                batch_size=args.dense_batch_size,
                max_chunk_bytes=int(args.dense_max_chunk_mb * 1024 * 1024),
                max_retries=args.max_retries,
                initial_backoff=args.retry_initial_backoff,
                max_backoff=args.retry_max_backoff,
                request_timeout=args.request_timeout,
                vector_dims=args.vector_dims,
                max_errors=args.max_errors,
                max_error_rate=args.max_error_rate,
                max_dense_shards=args.max_dense_shards,
            )

        finalize_index(
            client,
            index=args.index,
            alias=args.alias,
            final_refresh_interval=args.final_refresh_interval,
            final_replicas=args.final_replicas,
        )
        checkpoint["finalized"] = True
        checkpoint["alias"] = args.alias
        atomic_write_json(args.checkpoint, checkpoint)
        count = client.count(index=args.index)["count"]
        logging.info("Hybrid Elasticsearch import complete. Index count: %s", f"{count:,}")
        logging.info("Alias %s now points to %s", args.alias, args.index)
    finally:
        client.close()


if __name__ == "__main__":
    main()
