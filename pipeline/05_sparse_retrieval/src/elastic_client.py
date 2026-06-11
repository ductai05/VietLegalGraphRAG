"""Shared Elasticsearch utilities for the VietLegal sparse pipeline."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from elasticsearch import Elasticsearch

INDEX_NAME = "vietlegal_chunks_sparse_v1"
INDEX_ALIAS = "vietlegal_chunks_sparse_current"

PAYLOAD_FIELDS = [
    "chunk_id",
    "doc_id",
    "source",
    "document_number",
    "document_number_norm",
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
    "chunk_text",
    "contextual_text",
    "section_path",
    "procedure_name",
    "chunk_type",
    "parent_id",
    "prev_chunk_id",
    "next_chunk_id",
    "table_id",
    "raw_table_id",
    "summary_of",
    "answer_source",
    "do_not_answer_from_summary",
    "embed",
    "keyword_index",
    "token_estimate",
    "char_count",
    "quality_flags",
    "table_columns",
    "expansion_status",
]


def setup_logging(log_path: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else default
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



def batched(items: Sequence[Any], batch_size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def build_elasticsearch_client(
    url: str,
    *,
    api_key: str | None = None,
    username: str | None = None,
    password: str | None = None,
    verify_certs: bool = True,
    request_timeout: int = 60,
) -> Elasticsearch:
    kwargs: dict[str, Any] = {
        "request_timeout": request_timeout,
        "verify_certs": verify_certs,
    }
    if api_key:
        kwargs["api_key"] = api_key
    elif username and password:
        kwargs["basic_auth"] = (username, password)
    return Elasticsearch(url, **kwargs)


def json_ready(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
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
        return [json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    return value


def payload_from_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        field: json_ready(source.get(field))
        for field in PAYLOAD_FIELDS
        if field in source
    }



def iter_bulk_ndjson(
    docs: Iterable[dict[str, Any]],
    *,
    index: str,
) -> Iterator[str]:
    for doc in docs:
        action = {"index": {"_index": index, "_id": doc["chunk_id"]}}
        yield json.dumps(action, ensure_ascii=False)
        yield json.dumps(json_ready(doc), ensure_ascii=False)
