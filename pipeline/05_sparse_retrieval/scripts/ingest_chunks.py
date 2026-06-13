"""Bulk ingest prepared sparse payload into Elasticsearch."""

from __future__ import annotations

import os
import sys
for _key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_key, None)

import argparse
import logging
from pathlib import Path
from typing import Any, Iterator

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
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--request-timeout", type=int, default=300)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-verify-certs", action="store_true")
    parser.add_argument("--workers", type=int, default=2, help="Number of parallel ingestion workers.")
    parser.add_argument("--queue-size", type=int, default=2, help="Parallel queue size capacity.")
    parser.add_argument("--max-chunk-mb", type=int, default=20, help="Maximum bulk request size in MiB.")
    return parser.parse_args()


def make_actions_generator(
    parquet_file: pq.ParquetFile,
    start_row: int,
    index: str,
    batch_size: int = 10000,
) -> Iterator[dict[str, Any]]:
    seen = 0
    for batch in parquet_file.iter_batches(batch_size=batch_size):
        rows = batch.to_pylist()
        batch_end = seen + len(rows)
        if batch_end <= start_row:
            seen = batch_end
            continue
        if start_row > seen:
            rows = rows[start_row - seen :]
        seen = batch_end
        
        for row in rows:
            yield {
                "_op_type": "index",
                "_index": index,
                "_id": row["chunk_id"],
                "_source": json_ready(row),
            }


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
    if args.workers <= 0:
        raise ValueError("--workers must be positive")
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
    try:
        parquet_file = pq.ParquetFile(args.payload)
        total_rows = parquet_file.metadata.num_rows
        if processed_so_far > total_rows:
            raise ValueError(
                f"Checkpoint processed {processed_so_far:,} rows, "
                f"but payload only has {total_rows:,} rows"
            )
        indexed = int(checkpoint.get("indexed", processed_so_far))
        errors_total = int(checkpoint.get("errors", 0))
        error_samples = []

        logging.info(
            "Starting parallel ingestion: workers=%s batch=%s queue=%s processed_so_far=%s",
            args.workers,
            args.batch_size,
            args.queue_size,
            f"{processed_so_far:,}",
        )
        
        actions = make_actions_generator(parquet_file, processed_so_far, args.index)
        results = helpers.parallel_bulk(
            client,
            actions,
            thread_count=args.workers,
            chunk_size=args.batch_size,
            max_chunk_bytes=args.max_chunk_mb * 1024 * 1024,
            queue_size=args.queue_size,
            raise_on_error=False,
            raise_on_exception=False,
        )

        for success, info in results:
            processed_so_far += 1
            if success:
                indexed += 1
            else:
                errors_total += 1
                if len(error_samples) < 5:
                    error_samples.append(info)
            
            if processed_so_far % 50000 == 0:
                atomic_write_json(
                    checkpoint_path,
                    {
                        "payload": str(args.payload),
                        "index": args.index,
                        "processed": processed_so_far,
                        "indexed": indexed,
                        "errors": errors_total,
                        "total_rows": total_rows,
                        "error_samples": error_samples[:3] if error_samples else None,
                    },
                )
                logging.info(
                    "Processed %s/%s rows (indexed: %s, errors: %s)",
                    f"{processed_so_far:,}",
                    f"{total_rows:,}",
                    f"{indexed:,}",
                    f"{errors_total:,}",
                )

        # Final checkpoint
        atomic_write_json(
            checkpoint_path,
            {
                "payload": str(args.payload),
                "index": args.index,
                "processed": processed_so_far,
                "indexed": indexed,
                "errors": errors_total,
                "total_rows": total_rows,
                "error_samples": error_samples[:3] if error_samples else None,
            },
        )
        logging.info("Parallel ingestion complete. Total processed: %s rows", f"{processed_so_far:,}")
        
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
