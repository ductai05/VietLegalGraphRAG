"""Index and upload sparse payload to an Elasticsearch cluster (e.g., Elastic Cloud)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Resolve project root
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import pyarrow.parquet as pq
from elasticsearch import helpers

from src.elastic_client import (
    INDEX_ALIAS,
    INDEX_NAME,
    atomic_write_json,
    build_elasticsearch_client,
    json_ready,
    read_json,
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("ELASTIC_URL"))
    parser.add_argument("--api-key", default=os.environ.get("ELASTIC_API_KEY"))
    parser.add_argument("--username", default=os.environ.get("ELASTIC_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("ELASTIC_PASSWORD"))
    parser.add_argument(
        "--payload",
        type=Path,
        default=Path(os.environ.get("PAYLOAD_PATH")) if os.environ.get("PAYLOAD_PATH") else None,
        help="Path to the parquet file containing chunk payload",
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=ROOT_DIR / "mappings/vietlegal_chunks_sparse_v1.json",
        help="Path to the Elasticsearch mapping JSON file",
    )
    parser.add_argument("--index", default=os.environ.get("ELASTIC_INDEX", INDEX_NAME))
    parser.add_argument("--alias", default=os.environ.get("ELASTIC_ALIAS", INDEX_ALIAS))
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--request-timeout", type=int, default=120)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the index if it exists")
    parser.add_argument("--refresh", action="store_true", help="Refresh index after indexing")
    parser.add_argument("--no-verify-certs", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT_DIR / "config.env")
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


def update_alias(client: Any, index: str, alias: str) -> None:
    actions: list[dict[str, Any]] = []
    if client.indices.exists_alias(name=alias):
        current = client.indices.get_alias(name=alias)
        for cur_index in current.keys():
            actions.append({"remove": {"index": cur_index, "alias": alias}})
    actions.append({"add": {"index": index, "alias": alias}})
    client.indices.update_aliases(actions=actions)


def main() -> None:
    # Pre-parse env-file configuration
    temp_parser = argparse.ArgumentParser(add_help=False)
    temp_parser.add_argument("--env-file", type=Path, default=ROOT_DIR / "config.env")
    temp_args, _ = temp_parser.parse_known_args()
    
    load_env_file(temp_args.env_file)
    if not temp_args.env_file.exists():
        load_env_file(ROOT_DIR / ".env")

    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    if not args.url:
        logging.error("Elasticsearch URL is required (provide via --url or ELASTIC_URL env var)")
        sys.exit(1)
    if not args.payload:
        logging.error("Payload parquet path is required (provide via --payload or PAYLOAD_PATH env var)")
        sys.exit(1)
    if not args.payload.exists():
        logging.error("Payload file not found: %s", args.payload)
        sys.exit(1)
    if not args.mapping.exists():
        logging.error("Mapping file not found: %s", args.mapping)
        sys.exit(1)

    client = build_elasticsearch_client(
        args.url,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        verify_certs=not args.no_verify_certs,
        request_timeout=args.request_timeout,
    )

    try:
        # Load Elasticsearch mapping definitions
        with args.mapping.open("r", encoding="utf-8") as handle:
            mapping = json.load(handle)

        if "settings" in mapping:
            mapping["settings"].pop("number_of_shards", None)
            mapping["settings"].pop("number_of_replicas", None)

        exists = client.indices.exists(index=args.index)
        if exists and args.recreate:
            logging.info("Deleting existing index %s", args.index)
            client.indices.delete(index=args.index)
            exists = False

        if not exists:
            client.indices.create(index=args.index, **mapping)
            logging.info("Created index %s", args.index)
        else:
            logging.info("Index %s already exists", args.index)

        # Ingest payload content in batches
        checkpoint_path = args.checkpoint or Path.cwd() / f"{args.payload.stem}.cloud_ingest_checkpoint.json"
        checkpoint = read_json(checkpoint_path, {})
        if checkpoint and (
            checkpoint.get("payload") != str(args.payload)
            or checkpoint.get("index") != args.index
        ):
            checkpoint = {}

        processed_so_far = int(checkpoint.get("processed", checkpoint.get("indexed", 0)))
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
