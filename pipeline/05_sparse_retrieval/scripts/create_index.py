"""Create the versioned Elasticsearch sparse index."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.elastic_client import INDEX_NAME, build_elasticsearch_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--index", default=INDEX_NAME)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--no-verify-certs", action="store_true")
    parser.add_argument("--request-timeout", type=int, default=60)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    with args.mapping.open("r", encoding="utf-8") as handle:
        mapping = json.load(handle)
    client = build_elasticsearch_client(
        args.url,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        verify_certs=not args.no_verify_certs,
        request_timeout=args.request_timeout,
    )
    try:
        exists = client.indices.exists(index=args.index)
        if exists and args.recreate:
            logging.info("Deleting existing index %s", args.index)
            client.indices.delete(index=args.index)
            exists = False
        if exists:
            logging.info("Index %s already exists", args.index)
            return
        client.indices.create(index=args.index, **mapping)
        logging.info("Created index %s", args.index)
    finally:
        client.close()


if __name__ == "__main__":
    main()
