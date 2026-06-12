"""Prepare tokenized Elasticsearch payload from chunking output."""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path
import sys

import polars as pl
import pyarrow.parquet as pq
from tqdm.auto import tqdm

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.elastic_client import INDEX_NAME, atomic_write_json, iter_bulk_ndjson
from src.normalizer import (
    METADATA_COLUMNS,
    SPARSE_SCHEMA,
    bool_expr,
    int_expr,
    list_expr,
    normalize_sparse_record,
    string_expr,
)
from src.tokenizer import add_tokenized_fields

REQUIRED_CHUNK_COLUMNS = {
    "chunk_id",
    "doc_id",
    "chunk_text",
    "chunk_type",
    "keyword_index",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", default="v0.1")
    parser.add_argument("--index", default=INDEX_NAME)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--export-ndjson", action="store_true")
    parser.add_argument("--num-splits", type=int, default=None, help="Number of splits to divide the data into")
    parser.add_argument("--split-index", type=int, default=None, help="1-based index of the split to process")
    return parser.parse_args()


def require_columns(path: Path, required: set[str]) -> list[str]:
    columns = pl.scan_parquet(path).collect_schema().names()
    missing = required.difference(columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    return columns


def build_base_payload(args: argparse.Namespace, base_path: Path) -> dict[str, int]:
    chunk_columns = set(require_columns(args.chunks, REQUIRED_CHUNK_COLUMNS))
    metadata_columns = set(require_columns(args.metadata, {"id"}))

    chunks = (
        pl.scan_parquet(args.chunks)
        .filter(pl.col("keyword_index").cast(pl.Boolean, strict=False).fill_null(False))
        .filter(pl.col("chunk_text").cast(pl.Utf8, strict=False).fill_null("").str.len_chars() > 0)
        .select(
            "chunk_id",
            pl.col("doc_id").cast(pl.Int64, strict=False),
            "chunk_text",
            "chunk_type",
            string_expr("source", chunk_columns, alias="chunk_source"),
            string_expr("contextual_text", chunk_columns),
            list_expr("section_path", chunk_columns),
            string_expr("procedure_name", chunk_columns),
            bool_expr("embed", chunk_columns, default=False),
            bool_expr("keyword_index", chunk_columns, default=False),
            string_expr("parent_id", chunk_columns),
            string_expr("prev_chunk_id", chunk_columns),
            string_expr("next_chunk_id", chunk_columns),
            string_expr("table_id", chunk_columns),
            string_expr("raw_table_id", chunk_columns),
            string_expr("summary_of", chunk_columns),
            string_expr("answer_source", chunk_columns),
            bool_expr("do_not_answer_from_summary", chunk_columns),
            int_expr("token_estimate", chunk_columns),
            int_expr("char_count", chunk_columns),
            list_expr("quality_flags", chunk_columns),
            list_expr("table_columns", chunk_columns),
        )
    )

    if args.num_splits and args.split_index:
        if not (1 <= args.split_index <= args.num_splits):
            raise ValueError(f"split-index must be between 1 and {args.num_splits}")
        total_rows = chunks.select(pl.len()).collect().item()
        split_idx = args.split_index - 1
        chunk_size = (total_rows + args.num_splits - 1) // args.num_splits
        start_idx = split_idx * chunk_size
        length = min(chunk_size, max(0, total_rows - start_idx))
        chunks = chunks.slice(start_idx, length)
        logging.getLogger().info("Splitting data: processing split %d/%d (%d rows starting from index %d)", 
                                 args.split_index, args.num_splits, length, start_idx)

    metadata_select = [
        pl.col("id").cast(pl.Int64, strict=False),
        *[
            list_expr(name, metadata_columns)
            if name == "legal_sectors"
            else string_expr(
                name,
                metadata_columns,
                alias=("metadata_source" if name == "source" else name),
            )
            for name in METADATA_COLUMNS
            if name != "id"
        ],
        pl.lit(True).alias("_metadata_exists"),
    ]
    metadata = pl.scan_parquet(args.metadata).select(*metadata_select)
    joined = chunks.join(metadata, left_on="doc_id", right_on="id", how="left")
    missing_metadata = (
        joined.filter(pl.col("_metadata_exists").is_null())
        .select(pl.len())
        .collect()
        .item()
    )
    if missing_metadata:
        raise ValueError(f"{missing_metadata:,} keyword chunks have no metadata row")

    joined = joined.with_columns(
        pl.when(pl.col("chunk_source") != "")
        .then(pl.col("chunk_source"))
        .otherwise(pl.col("metadata_source"))
        .alias("source"),
        pl.lit("ok").alias("expansion_status"),
    ).drop(["chunk_source", "metadata_source", "_metadata_exists"])

    if args.limit:
        joined = joined.limit(args.limit)
    joined.sink_parquet(base_path, compression="zstd")

    stats = (
        pl.scan_parquet(base_path)
        .select(
            pl.len().alias("rows"),
            pl.col("chunk_id").n_unique().alias("unique_chunk_ids"),
            pl.col("doc_id").n_unique().alias("documents"),
        )
        .collect()
        .row(0, named=True)
    )
    if stats["rows"] != stats["unique_chunk_ids"]:
        raise ValueError("chunk_id is not unique in sparse base payload")
    return stats


def _process_row(row: dict) -> dict | None:
    record = normalize_sparse_record(row)
    if not record.get("chunk_id"):
        return None
    return add_tokenized_fields(record)


def tokenize_payload(
    base_path: Path,
    output_path: Path,
    *,
    batch_size: int,
    export_ndjson: bool,
    ndjson_path: Path,
    index: str,
) -> dict[str, int]:
    parts_dir = output_path.parent / f".{output_path.stem}_parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True)
    if export_ndjson:
        ndjson_path.unlink(missing_ok=True)

    parquet_file = pq.ParquetFile(base_path)
    total = parquet_file.metadata.num_rows
    ndjson_handle = ndjson_path.open("w", encoding="utf-8") if export_ndjson else None
    
    import multiprocessing
    num_workers = max(1, multiprocessing.cpu_count())
    ctx = multiprocessing.get_context("spawn")
    
    try:
        progress = tqdm(
            parquet_file.iter_batches(batch_size=batch_size),
            total=(total + batch_size - 1) // batch_size,
            desc="Tokenizing sparse payload",
            unit="batch",
        )
        with ctx.Pool(num_workers) as pool:
            for batch_idx, batch in enumerate(progress):
                docs = [
                    res for res in pool.map(_process_row, batch.to_pylist(), chunksize=100)
                    if res is not None
                ]
                if not docs:
                    continue
                part_path = parts_dir / f"part_{batch_idx:05d}.parquet"
                pl.DataFrame(docs, schema=SPARSE_SCHEMA, strict=False).write_parquet(
                    part_path,
                    compression="zstd",
                )
                if ndjson_handle is not None:
                    for line in iter_bulk_ndjson(docs, index=index):
                        ndjson_handle.write(line)
                        ndjson_handle.write("\n")
    finally:
        if ndjson_handle is not None:
            ndjson_handle.close()

    part_paths = sorted(parts_dir.glob("part_*.parquet"))
    if not part_paths:
        raise ValueError("No sparse documents were produced")
    pl.concat(
        [pl.scan_parquet(str(path)) for path in part_paths],
        how="diagonal_relaxed",
    ).sink_parquet(output_path, compression="zstd")
    shutil.rmtree(parts_dir)

    stats = (
        pl.scan_parquet(output_path)
        .select(
            pl.len().alias("rows"),
            pl.col("chunk_id").n_unique().alias("unique_chunk_ids"),
            pl.col("doc_id").n_unique().alias("documents"),
            (pl.col("chunk_text_vi") == "").sum().alias("empty_chunk_text_vi"),
            (pl.col("document_number") != "").sum().alias("documents_with_number"),
            (pl.col("document_number_norm") != "").sum().alias("documents_with_number_norm"),
        )
        .collect()
        .row(0, named=True)
    )
    if stats["rows"] != stats["unique_chunk_ids"]:
        raise ValueError("chunk_id is not unique in sparse payload")
    return stats


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if (args.num_splits is None) != (args.split_index is None):
        raise ValueError("--num-splits and --split-index must be used together")
        
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    
    split_suffix = f"_split_{args.split_index}" if args.split_index else ""
    output_path = args.output_dir / f"sparse_payload_{args.version}{split_suffix}.parquet"
    base_path = args.output_dir / f"sparse_base_{args.version}{split_suffix}.parquet"
    ndjson_path = args.output_dir / f"sparse_payload_{args.version}{split_suffix}.ndjson"

    base_stats = build_base_payload(args, base_path)
    logging.info("Sparse base payload rows: %s", f"{base_stats['rows']:,}")
    sparse_stats = tokenize_payload(
        base_path,
        output_path,
        batch_size=args.batch_size,
        export_ndjson=args.export_ndjson,
        ndjson_path=ndjson_path,
        index=args.index,
    )
    atomic_write_json(
        args.output_dir / "prepare_sparse_manifest.json",
        {
            "version": args.version,
            "chunks": str(args.chunks),
            "metadata": str(args.metadata),
            "base_output": str(base_path),
            "output": str(output_path),
            "ndjson": str(ndjson_path) if args.export_ndjson else None,
            "base_stats": base_stats,
            "stats": sparse_stats,
        },
    )
    logging.info("Wrote %s with %s rows", output_path, f"{sparse_stats['rows']:,}")


if __name__ == "__main__":
    main()
