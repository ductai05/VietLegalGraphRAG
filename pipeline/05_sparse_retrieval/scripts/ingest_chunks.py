"""Bulk ingest prepared sparse payload into Elasticsearch."""

from __future__ import annotations

import os
import sys
for _key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_key, None)

import argparse
import logging
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from elasticsearch import helpers

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.elastic_client import (
    INDEX_ALIAS,
    INDEX_NAME,
    atomic_write_json,
    build_elasticsearch_client,
    json_ready,
    read_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--index", default=INDEX_NAME)
    parser.add_argument("--alias", default=INDEX_ALIAS)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--request-timeout", type=int, default=120)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-verify-certs", action="store_true")
    return parser.parse_args()


def make_actions(rows: list[dict[str, Any]], index: str) -> list[dict[str, Any]]:
    return [
        {
            "_op_type": "index",
            "_index": index,
            "_id": row["chunk_id"],
            "_source": json_ready(row),
        }
        for row in rows
    ]


def update_alias(client, index: str, alias: str) -> None:
    actions: list[dict[str, Any]] = []
    if client.indices.exists_alias(name=alias):
        current = client.indices.get_alias(name=alias)
        for current_index in current.keys():
            actions.append({"remove": {"index": current_index, "alias": alias}})
    actions.append({"add": {"index": index, "alias": alias}})
    client.indices.update_aliases(actions=actions)


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    checkpoint_path = args.checkpoint or args.payload.with_suffix(".ingest_checkpoint.json")
    checkpoint = read_json(checkpoint_path, {})
    if checkpoint and (
        checkpoint.get("payload") != str(args.payload)
        or checkpoint.get("index") != args.index
    ):
        checkpoint = {}
    processed_so_far = int(checkpoint.get("processed", checkpoint.get("indexed", 0)))

    client = build_elasticsearch_client(
        args.url,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        verify_certs=not args.no_verify_certs,
        request_timeout=args.request_timeout,
    )
    parquet_file = pq.ParquetFile(args.payload)
    total_rows = parquet_file.metadata.num_rows
    if processed_so_far > total_rows:
        raise ValueError(
            f"Checkpoint processed {processed_so_far:,} rows, "
            f"but payload only has {total_rows:,} rows"
        )
    indexed = int(checkpoint.get("indexed", processed_so_far))
    errors_total = int(checkpoint.get("errors", 0))
    seen = 0
    try:
        for batch in parquet_file.iter_batches(batch_size=args.batch_size):
            rows = batch.to_pylist()
            batch_end = seen + len(rows)
            if batch_end <= processed_so_far:
                seen = batch_end
                continue
            if processed_so_far > seen:
                rows = rows[processed_so_far - seen :]
            seen = batch_end
            actions = make_actions(rows, args.index)
            ok, errors = helpers.bulk(
                client,
                actions,
                chunk_size=args.batch_size,
                max_retries=args.max_retries,
                request_timeout=args.request_timeout,
                raise_on_error=False,
            )
            if errors:
                errors_total += len(errors)
                atomic_write_json(
                    checkpoint_path,
                    {
                        "payload": str(args.payload),
                        "index": args.index,
                        "processed": processed_so_far,
                        "indexed": indexed,
                        "errors": errors_total,
                        "total_rows": total_rows,
                        "failed_batch_size": len(rows),
                        "error_samples": errors[:3],
                    },
                )
                logging.warning(
                    "Bulk ingest failed for %s actions. "
                    "See checkpoint for samples: %s",
                    f"{len(errors):,}",
                    checkpoint_path,
                )
            if ok != len(rows):
                logging.warning("Bulk ingest acknowledged %s/%s rows", f"{ok:,}", f"{len(rows):,}")
            processed_so_far += len(rows)
            indexed += ok
            atomic_write_json(
                checkpoint_path,
                {
                    "payload": str(args.payload),
                    "index": args.index,
                    "processed": processed_so_far,
                    "indexed": indexed,
                    "errors": errors_total,
                    "total_rows": total_rows,
                },
            )
            logging.info("Indexed %s/%s rows", f"{indexed:,}", f"{total_rows:,}")
        if args.refresh:
            client.indices.refresh(index=args.index)
        update_alias(client, args.index, args.alias)
        count = client.count(index=args.index)["count"]
        logging.info("Index %s count: %s", args.index, f"{count:,}")
        if count != total_rows:
            if count < total_rows - errors_total:
                raise ValueError(f"Elasticsearch count mismatch: expected >={total_rows - errors_total:,}, got {count:,}")
            logging.warning("Index count %s vs total %s (skipped %s errored docs)", f"{count:,}", f"{total_rows:,}", f"{errors_total:,}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
