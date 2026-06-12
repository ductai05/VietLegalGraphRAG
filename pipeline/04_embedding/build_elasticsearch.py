"""Upload embedding shards to Elasticsearch with bounded parallel bulk requests."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

try:
    from elasticsearch import Elasticsearch, helpers
except ModuleNotFoundError as exc:
    if exc.name != "elasticsearch":
        raise
    Elasticsearch = None
    helpers = None

sys.path.append(str(Path(__file__).resolve().parent))
from elasticsearch_common import (  # noqa: E402
    build_index_definition,
    make_index_action,
    resolve_credentials,
)
from embedding_common import (  # noqa: E402
    VECTOR_SIZE,
    atomic_write_json,
    file_fingerprint,
    read_json,
    setup_logging,
)

RETRY_STATUSES = (429, 502, 503, 504)


@dataclass(frozen=True)
class UploadResult:
    uploaded: int
    failed: int
    elapsed_seconds: float
    rows_per_second: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards-dir", type=Path, required=True)
    parser.add_argument(
        "--cloud-id",
        default=None,
        help="Elastic Cloud ID. Defaults to ELASTIC_CLOUD_ID.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Elasticsearch API key. Defaults to ELASTIC_API_KEY.",
    )
    parser.add_argument("--index", default="legal_chunks_dense_v1")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Concurrent bulk request workers. Start with 2 on Elastic Cloud trial.",
    )
    parser.add_argument(
        "--upsert-batch",
        type=int,
        default=500,
        help="Documents per bulk request. Benchmark before increasing.",
    )
    parser.add_argument(
        "--max-chunk-mb",
        type=int,
        default=20,
        help="Maximum encoded bulk request size in MiB.",
    )
    parser.add_argument(
        "--queue-size",
        type=int,
        default=2,
        help="Bounded queue between action generation and bulk workers.",
    )
    parser.add_argument(
        "--number-of-shards",
        type=int,
        default=1,
        help="Primary shards for a newly created index.",
    )
    parser.add_argument(
        "--final-replicas",
        type=int,
        default=0,
        help="Replica count restored after all selected shards finish.",
    )
    parser.add_argument(
        "--final-refresh-interval",
        default="5s",
        help="Refresh interval restored after ingestion completes.",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=300,
        help="Elasticsearch request timeout in seconds.",
    )
    parser.add_argument(
        "--max-shards",
        type=int,
        default=None,
        help="Optional source shard limit for benchmarking.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    positive = {
        "--workers": args.workers,
        "--upsert-batch": args.upsert_batch,
        "--max-chunk-mb": args.max_chunk_mb,
        "--queue-size": args.queue_size,
        "--number-of-shards": args.number_of_shards,
        "--request-timeout": args.request_timeout,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if args.final_replicas < 0:
        raise ValueError("--final-replicas cannot be negative")
    if args.max_shards is not None and args.max_shards <= 0:
        raise ValueError("--max-shards must be positive")


def _shorten(text: Any, max_len: int = 1000) -> str | None:
    if text is None:
        return None
    rendered = str(text)
    if len(rendered) <= max_len:
        return rendered
    return rendered[:max_len] + "... [truncated]"


def summarize_bulk_error(error_info: Any) -> dict[str, Any]:
    """Remove source/vector content from a bulk failure before logging it."""
    if not isinstance(error_info, dict):
        return {"reason": _shorten(error_info)}
    operation = next(
        (name for name in ("index", "create", "update", "delete") if name in error_info),
        None,
    )
    if operation is None:
        return {"raw_error_keys": list(error_info)}
    item = error_info.get(operation) or {}
    error = item.get("error") or {}
    caused_by = error.get("caused_by") if isinstance(error, dict) else None
    return {
        "op": operation,
        "status": item.get("status"),
        "_index": item.get("_index"),
        "_id": item.get("_id"),
        "error_type": error.get("type") if isinstance(error, dict) else None,
        "reason": _shorten(
            error.get("reason") if isinstance(error, dict) else error
        ),
        "caused_by_type": (
            caused_by.get("type") if isinstance(caused_by, dict) else None
        ),
        "caused_by_reason": _shorten(
            caused_by.get("reason") if isinstance(caused_by, dict) else None
        ),
    }


def _iter_actions(
    index: str,
    payload_df: Any,
    vectors: np.ndarray,
) -> Iterable[dict[str, Any]]:
    for row_index, row in enumerate(payload_df.iter_rows(named=True)):
        yield make_index_action(index, row, vectors[row_index])


def upload_shard(
    *,
    es: Any,
    index: str,
    payload_df: Any,
    vectors: np.ndarray,
    workers: int,
    batch_size: int,
    max_chunk_bytes: int,
    queue_size: int,
    parallel_bulk_fn: Callable[..., Iterable[tuple[bool, Any]]] | None = None,
) -> UploadResult:
    """Upload one source shard; raise unless every action succeeds."""
    if payload_df.height != len(vectors):
        raise ValueError(
            "Payload/vector row mismatch: "
            f"payload rows={payload_df.height}, vector rows={len(vectors)}"
        )
    for name, value in {
        "workers": workers,
        "batch_size": batch_size,
        "max_chunk_bytes": max_chunk_bytes,
        "queue_size": queue_size,
    }.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")

    bulk = parallel_bulk_fn
    if bulk is None:
        if helpers is None:
            raise ModuleNotFoundError(
                "Elasticsearch ingest requires the `elasticsearch` package. "
                "Install it with `python -m pip install elasticsearch`."
            )
        bulk = helpers.parallel_bulk

    uploaded = 0
    failures: list[dict[str, Any]] = []
    started = time.perf_counter()
    results = bulk(
        es,
        _iter_actions(index, payload_df, vectors),
        thread_count=workers,
        chunk_size=batch_size,
        max_chunk_bytes=max_chunk_bytes,
        queue_size=queue_size,
        raise_on_error=False,
        raise_on_exception=False,
        max_retries=5,
        initial_backoff=2,
        max_backoff=60,
        retry_on_status=RETRY_STATUSES,
        yield_ok=True,
    )
    for success, info in results:
        if success:
            uploaded += 1
        elif len(failures) < 10:
            failures.append(summarize_bulk_error(info))

    elapsed = max(time.perf_counter() - started, 1e-9)
    failed = payload_df.height - uploaded
    if failed:
        for position, failure in enumerate(failures, start=1):
            logging.error(
                "Bulk failure %s: %s",
                position,
                json.dumps(failure, ensure_ascii=False),
            )
        raise RuntimeError(
            f"Elasticsearch bulk upload failed for {failed:,} document(s); "
            "the shard was not checkpointed"
        )
    return UploadResult(
        uploaded=uploaded,
        failed=failed,
        elapsed_seconds=elapsed,
        rows_per_second=uploaded / elapsed,
    )


def upload_and_checkpoint_shard(
    *,
    es: Any,
    index: str,
    shard_key: str,
    payload_df: Any,
    vectors: np.ndarray,
    build_manifest: dict[str, Any],
    build_manifest_path: Path,
    workers: int,
    batch_size: int,
    max_chunk_bytes: int,
    queue_size: int,
    parallel_bulk_fn: Callable[..., Iterable[tuple[bool, Any]]] | None = None,
    write_manifest_fn: Callable[[Path, dict[str, Any]], None] = atomic_write_json,
) -> UploadResult:
    """Upload a complete shard before atomically recording its checkpoint."""
    result = upload_shard(
        es=es,
        index=index,
        payload_df=payload_df,
        vectors=vectors,
        workers=workers,
        batch_size=batch_size,
        max_chunk_bytes=max_chunk_bytes,
        queue_size=queue_size,
        parallel_bulk_fn=parallel_bulk_fn,
    )
    build_manifest.setdefault("shards", {})[shard_key] = {
        "status": "done",
        "rows": payload_df.height,
        "uploaded": result.uploaded,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "rows_per_second": round(result.rows_per_second, 3),
    }
    write_manifest_fn(build_manifest_path, build_manifest)
    return result


def _validate_existing_index(es: Any, index: str) -> None:
    mapping_response = es.indices.get_mapping(index=index)
    mapping = mapping_response[index]["mappings"]
    properties = mapping.get("properties", {})
    expected = build_index_definition(1)["mappings"]["properties"]
    vector = properties.get("vector", {})
    if vector.get("type") != "dense_vector" or vector.get("dims") != VECTOR_SIZE:
        raise ValueError(
            f"Existing index {index!r} has an incompatible vector mapping; "
            "rerun with --recreate"
        )
    incompatible = [
        field
        for field, definition in expected.items()
        if field != "vector"
        and properties.get(field, {}).get("type") != definition.get("type")
    ]
    if incompatible:
        raise ValueError(
            f"Existing index {index!r} has missing/incompatible fields "
            f"{incompatible}; rerun with --recreate"
        )


def ensure_index(
    es: Any,
    index: str,
    *,
    recreate: bool,
    number_of_shards: int,
) -> None:
    exists = bool(es.indices.exists(index=index))
    if exists and recreate:
        es.indices.delete(index=index)
        logging.info("Deleted existing index %s", index)
        exists = False
    if not exists:
        es.indices.create(
            index=index,
            body=build_index_definition(number_of_shards, number_of_replicas=0),
        )
        logging.info("Created index %s", index)
        return

    _validate_existing_index(es, index)
    es.indices.put_settings(
        index=index,
        settings={"index": {"refresh_interval": "-1", "number_of_replicas": 0}},
    )
    logging.info("Using existing compatible index %s", index)


def finalize_index(
    es: Any,
    index: str,
    *,
    refresh_interval: str,
    replicas: int,
) -> None:
    es.indices.put_settings(
        index=index,
        settings={
            "index": {
                "refresh_interval": refresh_interval,
                "number_of_replicas": replicas,
            }
        },
    )
    es.indices.refresh(index=index)


def main() -> None:
    args = parse_args()
    validate_args(args)
    cloud_id, api_key = resolve_credentials(args.cloud_id, args.api_key)
    if Elasticsearch is None:
        raise ModuleNotFoundError(
            "Elasticsearch ingest requires the `elasticsearch` package. "
            "Install it with `python -m pip install elasticsearch`."
        )
    try:
        import polars as pl
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Elasticsearch ingest requires `polars`. Install project requirements "
            "with `python -m pip install -r requirements.txt`."
        ) from exc

    source_manifest_path = args.shards_dir / "manifest.json"
    source_manifest = read_json(source_manifest_path)
    if not source_manifest.get("shards"):
        raise FileNotFoundError(f"Missing or empty manifest: {source_manifest_path}")

    args.shards_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(args.shards_dir / "elasticsearch_build.log")
    build_manifest_path = args.shards_dir / "elasticsearch_manifest.json"
    build_manifest = read_json(build_manifest_path, {"shards": {}})
    if args.recreate:
        build_manifest = {"shards": {}}
    if build_manifest.get("index") not in (None, args.index):
        raise ValueError(
            "Existing Elasticsearch manifest belongs to index "
            f"{build_manifest['index']!r}; use the matching --index or --recreate"
        )

    es = Elasticsearch(
        cloud_id=cloud_id,
        api_key=api_key,
        request_timeout=args.request_timeout,
        retry_on_timeout=True,
        max_retries=5,
    )
    try:
        info = es.info()
        logging.info("Connected to Elasticsearch cluster %s", info.get("cluster_name"))
        ensure_index(
            es,
            args.index,
            recreate=args.recreate,
            number_of_shards=args.number_of_shards,
        )

        completed = sorted(
            (key, item)
            for key, item in source_manifest["shards"].items()
            if item.get("status") == "done"
        )
        if args.max_shards is not None:
            completed = completed[: args.max_shards]
        if not completed:
            raise ValueError("No completed embedding shards were selected")

        build_manifest.update(
            {
                "index": args.index,
                "source_manifest_fingerprint": file_fingerprint(source_manifest_path),
                "workers": args.workers,
                "batch_size": args.upsert_batch,
                "max_chunk_mb": args.max_chunk_mb,
                "queue_size": args.queue_size,
            }
        )
        build_manifest.setdefault("shards", {})
        atomic_write_json(build_manifest_path, build_manifest)

        logging.info(
            "Uploading %s shard(s): workers=%s batch=%s max_chunk=%s MiB queue=%s",
            len(completed),
            args.workers,
            args.upsert_batch,
            args.max_chunk_mb,
            args.queue_size,
        )
        total_uploaded = 0
        for ordinal, (shard_key, shard_info) in enumerate(completed, start=1):
            previous = build_manifest["shards"].get(shard_key, {})
            if (
                previous.get("status") == "done"
                and previous.get("rows") == shard_info["rows"]
            ):
                logging.info(
                    "Skipping completed shard %s (%s/%s)",
                    shard_key,
                    ordinal,
                    len(completed),
                )
                continue

            payload_path = args.shards_dir / shard_info["payload"]
            vector_path = args.shards_dir / shard_info["vectors"]
            logging.info(
                "Uploading shard %s (%s/%s): %s rows",
                shard_key,
                ordinal,
                len(completed),
                f"{shard_info['rows']:,}",
            )
            payload_df = pl.read_parquet(payload_path, glob=False)
            vectors = np.load(vector_path, mmap_mode="r")
            result = upload_and_checkpoint_shard(
                es=es,
                index=args.index,
                shard_key=shard_key,
                payload_df=payload_df,
                vectors=vectors,
                build_manifest=build_manifest,
                build_manifest_path=build_manifest_path,
                workers=args.workers,
                batch_size=args.upsert_batch,
                max_chunk_bytes=args.max_chunk_mb * 1024 * 1024,
                queue_size=args.queue_size,
            )
            total_uploaded += result.uploaded
            logging.info(
                "Completed shard %s: %s rows in %.1fs (%.1f rows/s)",
                shard_key,
                f"{result.uploaded:,}",
                result.elapsed_seconds,
                result.rows_per_second,
            )

        selected_complete = all(
            build_manifest["shards"].get(key, {}).get("status") == "done"
            and build_manifest["shards"][key].get("rows") == item["rows"]
            for key, item in completed
        )
        if not selected_complete:
            raise RuntimeError("Selected shards are not fully checkpointed")
        finalize_index(
            es,
            args.index,
            refresh_interval=args.final_refresh_interval,
            replicas=args.final_replicas,
        )
        build_manifest["finalized"] = True
        build_manifest["final_refresh_interval"] = args.final_refresh_interval
        build_manifest["final_replicas"] = args.final_replicas
        atomic_write_json(build_manifest_path, build_manifest)
        logging.info(
            "Elasticsearch indexing complete: uploaded %s rows in this run",
            f"{total_uploaded:,}",
        )
    finally:
        es.close()


if __name__ == "__main__":
    main()
