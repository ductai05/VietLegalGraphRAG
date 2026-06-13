"""Merge multiple split sparse payload parquet files into a single payload."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

import polars as pl

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from src.elastic_client import atomic_write_json

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dirs", type=Path, nargs="+", required=True, 
                        help="Directories containing the split sparse_payload_*.parquet files")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Directory to save the merged parquet file")
    parser.add_argument("--version", default="v0.1")
    return parser.parse_args()


def stream_merge_parquet(input_paths: list[Path], output_path: Path, batch_size: int = 100000) -> int:
    import pyarrow.parquet as pq
    first_file = pq.ParquetFile(str(input_paths[0]))
    schema = first_file.schema.to_arrow_schema()
    total_rows = 0
    with pq.ParquetWriter(str(output_path), schema, compression="zstd") as writer:
        for path in input_paths:
            logging.info("Streaming %s to output...", path.name)
            pf = pq.ParquetFile(str(path))
            for batch in pf.iter_batches(batch_size=batch_size):
                writer.write_batch(batch)
                total_rows += batch.num_rows
    return total_rows


def main() -> None:
    import pyarrow.parquet as pq
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Collect all parquet files to merge
    parquet_files = []
    base_parquet_files = []
    
    for in_dir in args.input_dirs:
        if not in_dir.exists():
            logging.warning("Input directory does not exist: %s", in_dir)
            continue
            
        payloads = list(in_dir.glob(f"sparse_payload_{args.version}_split_*.parquet"))
        parquet_files.extend(payloads)
        
        bases = list(in_dir.glob(f"sparse_base_{args.version}_split_*.parquet"))
        base_parquet_files.extend(bases)
        
    if not parquet_files:
        raise ValueError(f"No sparse_payload_{args.version}_split_*.parquet files found in provided input directories.")
        
    parquet_files.sort(key=lambda p: int(p.stem.split('_split_')[-1]))
    base_parquet_files.sort(key=lambda p: int(p.stem.split('_split_')[-1]))

    split_indices = [int(p.stem.split('_split_')[-1]) for p in parquet_files]
    expected_splits = list(range(1, len(parquet_files) + 1))
    if split_indices != expected_splits:
        raise ValueError(f"Missing or duplicate split files. Found splits: {split_indices}, expected: {expected_splits}")

    if base_parquet_files:
        base_split_indices = [int(p.stem.split('_split_')[-1]) for p in base_parquet_files]
        if base_split_indices != expected_splits:
            raise ValueError(f"Base split files mismatch. Found base splits: {base_split_indices}, expected: {expected_splits}")
        
    logging.info("Found %d split payloads to merge.", len(parquet_files))
    
    output_path = args.output_dir / f"sparse_payload_{args.version}.parquet"
    base_output_path = args.output_dir / f"sparse_base_{args.version}.parquet"

    expected_payload_rows = sum(
        pq.ParquetFile(str(path)).metadata.num_rows
        for path in parquet_files
    )
    expected_base_rows = 0
    if base_parquet_files:
        expected_base_rows = sum(
            pq.ParquetFile(str(path)).metadata.num_rows
            for path in base_parquet_files
        )
    
    # Merge payload
    logging.info("Merging sparse payload files...")
    merged_payload_rows = stream_merge_parquet(parquet_files, output_path)
    
    # Merge base
    logging.info("Merging sparse base files...")
    merged_base_rows = 0
    if base_parquet_files:
        merged_base_rows = stream_merge_parquet(base_parquet_files, base_output_path)
    
    # Generate stats in a memory-efficient way
    logging.info("Calculating merged payload stats...")
    stats = {
        "rows": merged_payload_rows,
        "unique_chunk_ids": merged_payload_rows, # Guaranteed by disjoint split slicing
        "documents": pl.scan_parquet(str(output_path), glob=False).select(pl.col("doc_id").n_unique()).collect().item()
    }
    
    base_stats = {}
    if base_parquet_files:
        logging.info("Calculating merged base stats...")
        base_stats = {
            "rows": merged_base_rows,
            "unique_chunk_ids": merged_base_rows, # Guaranteed by disjoint split slicing
            "documents": pl.scan_parquet(str(base_output_path), glob=False).select(pl.col("doc_id").n_unique()).collect().item()
        }
    
    if stats["rows"] != expected_payload_rows:
        raise ValueError(
            f"Merged payload row count ({stats['rows']}) does not match the sum of individual split rows ({expected_payload_rows})."
        )
        
    if base_parquet_files:
        if base_stats["rows"] != expected_base_rows:
            raise ValueError(
                f"Merged base row count ({base_stats['rows']}) does not match the sum of individual split rows ({expected_base_rows})."
            )
        
    logging.info("Successfully merged %d files.", len(parquet_files))
    logging.info("Total rows in merged payload: %s", f"{stats['rows']:,}")
    
    atomic_write_json(
        args.output_dir / "prepare_sparse_manifest_merged.json",
        {
            "version": args.version,
            "base_output": str(base_output_path),
            "output": str(output_path),
            "base_stats": base_stats,
            "stats": stats,
            "merged_from": [str(p) for p in parquet_files],
        },
    )

if __name__ == "__main__":
    main()
