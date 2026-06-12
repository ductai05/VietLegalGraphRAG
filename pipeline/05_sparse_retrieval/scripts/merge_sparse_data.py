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


def main() -> None:
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
        pl.scan_parquet(str(path)).select(pl.len()).collect().item()
        for path in parquet_files
    )
    expected_base_rows = 0
    if base_parquet_files:
        expected_base_rows = sum(
            pl.scan_parquet(str(path)).select(pl.len()).collect().item()
            for path in base_parquet_files
        )
    
    # Merge payload
    logging.info("Merging sparse payload files...")
    pl.concat(
        [pl.scan_parquet(str(path)) for path in parquet_files],
        how="diagonal_relaxed",
    ).sink_parquet(output_path, compression="zstd")
    
    # Merge base
    logging.info("Merging sparse base files...")
    if base_parquet_files:
        pl.concat(
            [pl.scan_parquet(str(path)) for path in base_parquet_files],
            how="diagonal_relaxed",
        ).sink_parquet(base_output_path, compression="zstd")
    
    # Generate stats
    stats = (
        pl.scan_parquet(output_path)
        .select(
            pl.len().alias("rows"),
            pl.col("chunk_id").n_unique().alias("unique_chunk_ids"),
            pl.col("doc_id").n_unique().alias("documents"),
        )
        .collect()
        .row(0, named=True)
    )
    
    base_stats = {}
    if base_parquet_files:
        base_stats = (
            pl.scan_parquet(base_output_path)
            .select(
                pl.len().alias("rows"),
                pl.col("chunk_id").n_unique().alias("unique_chunk_ids"),
                pl.col("doc_id").n_unique().alias("documents"),
            )
            .collect()
            .row(0, named=True)
        )
    
    if stats["rows"] != expected_payload_rows:
        raise ValueError(
            f"Merged payload row count ({stats['rows']}) does not match the sum of individual split rows ({expected_payload_rows})."
        )
    if stats["rows"] != stats["unique_chunk_ids"]:
        raise ValueError("chunk_id is not unique in the merged sparse payload.")
        
    if base_parquet_files:
        if base_stats["rows"] != expected_base_rows:
            raise ValueError(
                f"Merged base row count ({base_stats['rows']}) does not match the sum of individual split rows ({expected_base_rows})."
            )
        if base_stats["rows"] != base_stats["unique_chunk_ids"]:
            raise ValueError("chunk_id is not unique in the merged sparse base payload.")
        
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
