import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from elasticsearch import Elasticsearch, helpers
from elasticsearch.helpers import BulkIndexError

sys.path.append(str(Path(__file__).resolve().parent))
from embedding_common import read_json, stable_point_id  # noqa: E402


VECTOR_DIMS = 1024


def parse_args():
    parser = argparse.ArgumentParser(description="Upload vector shards to Elastic Cloud")
    parser.add_argument("--shards-dir", type=Path, required=True)
    parser.add_argument("--cloud-id", required=True, help="Elastic Cloud ID")
    parser.add_argument("--api-key", required=True, help="Elasticsearch API Key")
    parser.add_argument("--index", default="legal_chunks_dense_v1")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument(
        "--upsert-batch",
        type=int,
        default=100,
        help="Bulk batch size. For Elastic Cloud trial, 50-100 is safer than 500.",
    )
    parser.add_argument(
        "--max-shards",
        type=int,
        default=None,
        help="Optional limit for testing, e.g. --max-shards 3",
    )
    return parser.parse_args()


def safe_str(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, float) and math.isnan(value):
        return ""

    return str(value)


def ensure_index(es: Elasticsearch, index: str, recreate: bool):
    if recreate and es.indices.exists(index=index):
        es.indices.delete(index=index)
        print(f"Deleted existing index {index}")

    if es.indices.exists(index=index):
        print(f"Using existing index {index}")
        return

    mapping = {
        "settings": {
            "index": {
                # Faster bulk indexing. Set back to "1s" after ingest if needed.
                "refresh_interval": "-1",
            }
        },
        "mappings": {
            "dynamic": "true",
            "properties": {
                "chunk_id": {"type": "keyword"},

                # IMPORTANT:
                # doc_id is an identifier, not a number for math.
                # Some values exceed Elasticsearch integer range.
                "doc_id": {"type": "keyword"},

                "chunk_type": {"type": "keyword"},
                "title": {"type": "text"},
                "legal_type": {"type": "keyword"},
                "issuing_authority": {"type": "keyword"},
                "effect_status": {"type": "keyword"},
                "vector": {
                    "type": "dense_vector",
                    "dims": VECTOR_DIMS,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    }

    es.indices.create(index=index, body=mapping)
    print(f"Created index {index}")


def _shorten(text, max_len=1000):
    if text is None:
        return None

    text = str(text)
    if len(text) <= max_len:
        return text

    return text[:max_len] + "... [truncated]"


def _summarize_bulk_error(err: dict) -> dict:
    """
    Remove data/_source/vector from Elasticsearch bulk errors.
    This keeps logs readable when each doc contains a 1024-dim vector.
    """
    op_type = None
    item = None

    for candidate in ("index", "create", "update", "delete"):
        if candidate in err:
            op_type = candidate
            item = err[candidate]
            break

    if item is None:
        return {"raw_error_keys": list(err.keys())}

    error = item.get("error", {})
    caused_by = error.get("caused_by", {}) if isinstance(error, dict) else {}
    nested_caused_by = (
        caused_by.get("caused_by", {}) if isinstance(caused_by, dict) else {}
    )

    return {
        "op": op_type,
        "status": item.get("status"),
        "_index": item.get("_index"),
        "_id": item.get("_id"),
        "error_type": error.get("type") if isinstance(error, dict) else None,
        "reason": _shorten(error.get("reason") if isinstance(error, dict) else error),
        "caused_by_type": caused_by.get("type") if isinstance(caused_by, dict) else None,
        "caused_by_reason": _shorten(
            caused_by.get("reason") if isinstance(caused_by, dict) else None
        ),
        "nested_caused_by_type": (
            nested_caused_by.get("type") if isinstance(nested_caused_by, dict) else None
        ),
        "nested_caused_by_reason": _shorten(
            nested_caused_by.get("reason")
            if isinstance(nested_caused_by, dict)
            else None
        ),
    }


def run_bulk(es: Elasticsearch, actions: list):
    try:
        success, errors = helpers.bulk(
            es,
            actions,
            raise_on_error=False,
            raise_on_exception=False,
            request_timeout=300,
            max_retries=5,
            initial_backoff=2,
            max_backoff=60,
        )

        if errors:
            print(f"\n[ERROR] Bulk had {len(errors)} failed document(s). Success={success}")

            for i, err in enumerate(errors[:10], start=1):
                slim_error = _summarize_bulk_error(err)
                print(f"\n  Error {i}:")
                print(json.dumps(slim_error, ensure_ascii=False, indent=2))

            raise RuntimeError(f"Bulk had {len(errors)} failed document(s).")

        return success

    except BulkIndexError as e:
        print(f"\n[ERROR] BulkIndexError: {len(e.errors)} document(s) failed to index.")

        for i, err in enumerate(e.errors[:10], start=1):
            slim_error = _summarize_bulk_error(err)
            print(f"\n  Error {i}:")
            print(json.dumps(slim_error, ensure_ascii=False, indent=2))

        raise


def make_action(args, row: dict, vector: np.ndarray) -> dict:
    chunk_id = safe_str(row.get("chunk_id"))
    if not chunk_id:
        raise ValueError("Missing chunk_id")

    vec = np.asarray(vector, dtype=np.float32)

    if vec.ndim != 1 or vec.shape[0] != VECTOR_DIMS:
        raise ValueError(f"Bad vector shape for chunk_id={chunk_id}: {vec.shape}")

    if not np.isfinite(vec).all():
        raise ValueError(f"Vector contains NaN/Inf for chunk_id={chunk_id}")

    return {
        "_index": args.index,
        "_id": str(stable_point_id(chunk_id)),
        "_source": {
            "chunk_id": chunk_id,

            # IMPORTANT:
            # Store as string because values like 10000174386 exceed int32.
            "doc_id": safe_str(row.get("doc_id")),

            "chunk_type": safe_str(row.get("chunk_type")),
            "title": safe_str(row.get("title")),
            "legal_type": safe_str(row.get("legal_type")),
            "issuing_authority": safe_str(row.get("issuing_authority")),
            "effect_status": safe_str(row.get("effect_status")),
            "vector": vec.tolist(),
        },
    }


def main():
    args = parse_args()

    source_manifest_path = args.shards_dir / "manifest.json"
    source_manifest = read_json(source_manifest_path)

    if not source_manifest:
        raise FileNotFoundError(f"Missing or empty manifest: {source_manifest_path}")

    es = Elasticsearch(
        cloud_id=args.cloud_id,
        api_key=args.api_key,
        request_timeout=120,
        retry_on_timeout=True,
        max_retries=5,
    )

    info = es.info()
    print(f"Connected to Elasticsearch cluster: {info.get('cluster_name')}")

    ensure_index(es, args.index, args.recreate)

    completed = sorted(
        [
            (key, info)
            for key, info in source_manifest["shards"].items()
            if info.get("status") == "done"
        ]
    )

    if args.max_shards is not None:
        completed = completed[: args.max_shards]

    print(f"Uploading {len(completed)} shard(s) to Elastic Cloud...")

    total_uploaded = 0
    total_skipped = 0

    for shard_key, shard_info in completed:
        payload_path = args.shards_dir / shard_info["payload"]
        vector_path = args.shards_dir / shard_info["vectors"]

        print(f"\nShard {shard_key}")
        print(f"  payload: {payload_path}")
        print(f"  vectors: {vector_path}")

        payload_df = pl.read_parquet(payload_path)
        vectors = np.load(vector_path, mmap_mode="r")

        if payload_df.height != vectors.shape[0]:
            raise ValueError(
                f"Row/vector count mismatch in shard {shard_key}: "
                f"payload rows={payload_df.height}, vectors={vectors.shape[0]}"
            )

        rows = payload_df.to_dicts()
        actions = []

        shard_uploaded = 0
        shard_skipped = 0

        for row_index in range(payload_df.height):
            try:
                action = make_action(args, rows[row_index], vectors[row_index])
            except Exception as e:
                shard_skipped += 1
                total_skipped += 1
                print(
                    f"[WARN] Skip bad row: shard={shard_key}, "
                    f"row_index={row_index}, error={e}"
                )
                continue

            actions.append(action)

            if len(actions) >= args.upsert_batch:
                uploaded = run_bulk(es, actions)
                shard_uploaded += uploaded
                total_uploaded += uploaded
                actions = []

        if actions:
            uploaded = run_bulk(es, actions)
            shard_uploaded += uploaded
            total_uploaded += uploaded

        print(
            f"  Uploaded shard {shard_key}: "
            f"uploaded={shard_uploaded}, skipped={shard_skipped}"
        )

    # Restore refresh interval after ingest.
    # Keep replicas=0 if this is a small/trial cluster.
    es.indices.put_settings(
        index=args.index,
        settings={
            "index": {
                "refresh_interval": "1s",
            }
        },
    )

    es.indices.refresh(index=args.index)

    print("\nElastic Cloud indexing complete.")
    print(f"Total uploaded: {total_uploaded}")
    print(f"Total skipped: {total_skipped}")


if __name__ == "__main__":
    main()