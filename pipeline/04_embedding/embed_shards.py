"""Encode a frozen embedding payload into resumable float16 vector shards."""

from __future__ import annotations

import argparse
import gc
import logging
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow.parquet as pq

from embedding_common import (
    MODEL_NAME,
    PAYLOAD_FIELDS,
    VECTOR_SIZE,
    atomic_write_json,
    encode_texts,
    file_fingerprint,
    load_encoder,
    read_json,
    setup_logging,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--token-budget",
        type=int,
        default=None,
        help="Maximum padded tokens per batch; use with a larger --batch-size.",
    )
    parser.add_argument(
        "--no-sort-by-length",
        action="store_true",
        help="Disable length bucketing (slower when text lengths vary).",
    )
    parser.add_argument(
        "--attn-implementation",
        choices=["eager", "sdpa", "flash_attention_2"],
        default=None,
    )
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--shard-size", type=int, default=10_000)
    parser.add_argument("--shard-start", type=int, default=0, help="First shard index to encode.")
    parser.add_argument("--shard-stop", type=int, default=None, help="Exclusive shard index.")
    parser.add_argument("--limit", type=int, default=None, help="Debug limit across all shards.")
    parser.add_argument(
        "--include-text-in-payload",
        action="store_true",
        help="Also save chunk_text in payload shards for --include-text Qdrant builds.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.shard_start < 0 or (
        args.shard_stop is not None and args.shard_stop <= args.shard_start
    ):
        raise ValueError("--shard-stop must be greater than --shard-start")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(args.output_dir / "embed_run.log")
    manifest_path = args.output_dir / "manifest.json"
    payload_fingerprint = file_fingerprint(args.payload)
    manifest = read_json(manifest_path)
    if manifest and manifest.get("payload_fingerprint") != payload_fingerprint:
        raise ValueError("Existing manifest belongs to a different payload file")

    tokenizer, model, device, revision = load_encoder(
        args.model, args.device, args.cache_dir, args.attn_implementation
    )
    config = {
        "embedding_model": args.model,
        "model_revision": revision,
        "payload_fingerprint": payload_fingerprint,
        "max_length": args.max_length,
        "normalize": True,
        "vector_dtype": "float16",
        "vector_size": VECTOR_SIZE,
        "shard_size": args.shard_size,
        "shard_start": args.shard_start,
        "shard_stop": args.shard_stop,
        "include_text_in_payload": args.include_text_in_payload,
    }
    if manifest.get("shards"):
        changed = [
            key for key, value in config.items()
            if key in manifest and manifest[key] != value
        ]
        if changed:
            raise ValueError(
                f"Existing shards use different settings {changed}; use a new output directory"
            )
    manifest.setdefault("shards", {})
    manifest.update(config)
    atomic_write_json(manifest_path, manifest)

    parquet_file = pq.ParquetFile(args.payload)
    seen = 0
    for shard_index, record_batch in enumerate(
        parquet_file.iter_batches(batch_size=args.shard_size)
    ):
        if shard_index < args.shard_start:
            continue
        if args.shard_stop is not None and shard_index >= args.shard_stop:
            break
        if args.limit is not None and seen >= args.limit:
            break
        shard = pl.from_arrow(record_batch)
        if args.limit is not None:
            shard = shard.head(args.limit - seen)
        if shard.is_empty():
            break

        shard_key = f"{shard_index:05d}"
        vector_path = args.output_dir / f"vectors_shard_{shard_key}.npy"
        payload_path = args.output_dir / f"payload_shard_{shard_key}.parquet"
        previous = manifest["shards"].get(shard_key, {})
        if (
            previous.get("status") == "done"
            and previous.get("rows") == shard.height
            and vector_path.exists()
            and payload_path.exists()
        ):
            logging.info("Skipping completed shard %s", shard_key)
            seen += shard.height
            continue

        logging.info("Encoding shard %s (%s rows)", shard_key, f"{shard.height:,}")
        vectors = encode_texts(
            shard["contextual_text"].fill_null("").to_list(),
            tokenizer,
            model,
            device,
            batch_size=args.batch_size,
            max_length=args.max_length,
            is_query=False,
            sort_by_length=not args.no_sort_by_length,
            token_budget=args.token_budget,
        )
        if vectors.shape != (shard.height, VECTOR_SIZE):
            raise ValueError(f"Unexpected vector shape {vectors.shape} for shard {shard_key}")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(vectors).all() or not np.allclose(norms, 1.0, atol=1e-3):
            raise ValueError(f"Invalid or non-normalized vectors in shard {shard_key}")

        vector_temp = vector_path.with_suffix(".npy.tmp")
        payload_temp = payload_path.with_suffix(".parquet.tmp")
        with vector_temp.open("wb") as handle:
            np.save(handle, vectors.astype(np.float16))
        payload_columns = PAYLOAD_FIELDS + (
            ["chunk_text"] if args.include_text_in_payload else []
        )
        shard.select(payload_columns).write_parquet(payload_temp, compression="zstd")
        vector_temp.replace(vector_path)
        payload_temp.replace(payload_path)

        manifest["shards"][shard_key] = {
            "status": "done",
            "rows": shard.height,
            "first_chunk_id": shard["chunk_id"][0],
            "last_chunk_id": shard["chunk_id"][-1],
            "vectors": vector_path.name,
            "payload": payload_path.name,
        }
        manifest["completed_rows"] = sum(
            item["rows"]
            for item in manifest["shards"].values()
            if item.get("status") == "done"
        )
        atomic_write_json(manifest_path, manifest)
        seen += shard.height
        del shard, vectors
        gc.collect()

    logging.info("Embedding complete: %s rows", f"{manifest.get('completed_rows', 0):,}")


if __name__ == "__main__":
    main()
