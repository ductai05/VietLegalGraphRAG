"""Filter chunks, join metadata, and create the frozen embedding payload."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import polars as pl

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from embedding_common import atomic_write_json, file_fingerprint, setup_logging

REQUIRED_CHUNK_COLUMNS = {
    "chunk_id",
    "doc_id",
    "chunk_text",
    "chunk_type",
    "embed",
}
METADATA_COLUMNS = [
    "id",
    "document_number",
    "title",
    "legal_type",
    "issuing_authority",
    "issuance_date",
    "effect_date",
    "effectless_date",
    "effect_status",
    "linh_vuc",
    "nganh",
    "pham_vi",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", default="v0.1")
    parser.add_argument("--chunker-version", default="unknown")
    parser.add_argument(
        "--keep-existing-context",
        action="store_true",
        help="Keep contextual_text from chunking instead of rebuilding it with metadata.",
    )
    return parser.parse_args()


def require_columns(path: Path, required: set[str]) -> list[str]:
    columns = pl.scan_parquet(path, glob=False).collect_schema().names()
    missing = required.difference(columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    return columns


def string_col(name: str, available: set[str]) -> pl.Expr:
    if name in available:
        return pl.col(name).cast(pl.Utf8, strict=False).fill_null("")
    return pl.lit("").alias(name)


def list_col(name: str, available: set[str]) -> pl.Expr:
    if name in available:
        return pl.col(name).fill_null([])
    return pl.lit([], dtype=pl.List(pl.Utf8)).alias(name)


def bool_col(name: str, available: set[str], default: bool = False) -> pl.Expr:
    if name in available:
        return pl.col(name).cast(pl.Boolean, strict=False).fill_null(default)
    return pl.lit(default).alias(name)


def date_ts_expr(name: str) -> pl.Expr:
    value = pl.col(name).cast(pl.Utf8, strict=False).str.strip_chars()
    parsed = pl.coalesce(
        value.str.strptime(pl.Date, "%Y-%m-%d", strict=False),
        value.str.strptime(pl.Date, "%d/%m/%Y", strict=False),
        value.str.strptime(pl.Date, "%d-%m-%Y", strict=False),
        value.str.strptime(pl.Date, "%Y/%m/%d", strict=False),
    )
    return parsed.dt.strftime("%Y%m%d").cast(pl.Int64, strict=False).alias(f"{name}_ts")


def build_contextual_text_expr() -> pl.Expr:
    document = (
        pl.when((pl.col("document_number") != "") | (pl.col("title") != ""))
        .then(
            pl.concat_str(
                [pl.lit("Văn bản: "), pl.col("document_number"), pl.lit(" - "), pl.col("title")]
            ).str.strip_chars(" -")
        )
        .otherwise(None)
    )
    authority = (
        pl.when(pl.col("issuing_authority") != "")
        .then(pl.concat_str([pl.lit("Cơ quan: "), pl.col("issuing_authority")]))
        .otherwise(None)
    )
    issued = (
        pl.when(pl.col("issuance_date") != "")
        .then(pl.concat_str([pl.lit("Ngày ban hành: "), pl.col("issuance_date")]))
        .otherwise(None)
    )
    section = (
        pl.when(pl.col("section_path").list.len() > 0)
        .then(pl.concat_str([pl.lit("Mục: "), pl.col("section_path").list.join(" > ")]))
        .otherwise(None)
    )
    procedure = (
        pl.when(pl.col("procedure_name") != "")
        .then(pl.concat_str([pl.lit("Thủ tục: "), pl.col("procedure_name")]))
        .otherwise(None)
    )
    prefix = pl.concat_list([document, authority, issued, section, procedure]).list.drop_nulls().list.join(" | ")
    return (
        pl.when(prefix.str.len_chars() > 0)
        .then(pl.concat_str([pl.lit("["), prefix, pl.lit("]\n\n"), pl.col("chunk_text")]))
        .otherwise(pl.col("chunk_text"))
        .alias("contextual_text")
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(args.output_dir / "prepare.log")

    chunk_columns = set(require_columns(args.chunks, REQUIRED_CHUNK_COLUMNS))
    metadata_columns = set(require_columns(args.metadata, {"id"}))
    output_path = args.output_dir / f"embed_payload_{args.version}.parquet"

    chunk_optional = [
        "source",
        "contextual_text",
        "section_path",
        "procedure_name",
        "parent_id",
        "raw_table_id",
        "table_id",
        "summary_of",
        "answer_source",
        "do_not_answer_from_summary",
        "table_columns",
    ]
    chunks = (
        pl.scan_parquet(args.chunks, glob=False)
        .filter(pl.col("embed").fill_null(False))
        .filter(pl.col("chunk_type") != "raw_table")
        .select(
            "chunk_id",
            "doc_id",
            "chunk_text",
            "chunk_type",
            *[string_col(name, chunk_columns) for name in chunk_optional if name not in {"section_path", "table_columns", "do_not_answer_from_summary"}],
            list_col("section_path", chunk_columns),
            list_col("table_columns", chunk_columns),
            bool_col("do_not_answer_from_summary", chunk_columns),
            *([pl.col("quality_flags")] if "quality_flags" in chunk_columns else []),
            *([pl.col("quality_flags_json")] if "quality_flags_json" in chunk_columns else []),
        )
    )
    if "quality_flags" in chunk_columns:
        chunks = chunks.filter(
            ~pl.col("quality_flags").fill_null([]).list.contains("hard_char_split")
        ).drop("quality_flags")
    elif "quality_flags_json" in chunk_columns:
        chunks = chunks.filter(
            ~pl.col("quality_flags_json").fill_null("").str.contains("hard_char_split")
        ).drop("quality_flags_json")

    metadata = pl.scan_parquet(args.metadata, glob=False).select(
        *[
            (pl.col(name).cast(pl.Int64, strict=False) if name == "id" else string_col(name, metadata_columns))
            for name in METADATA_COLUMNS
        ],
        pl.lit(True).alias("_metadata_exists"),
    )
    payload = chunks.join(metadata, left_on="doc_id", right_on="id", how="left").with_columns(
        *[string_col(name, set(METADATA_COLUMNS)) for name in METADATA_COLUMNS if name != "id"],
        date_ts_expr("issuance_date"),
        date_ts_expr("effect_date"),
        date_ts_expr("effectless_date"),
    )
    missing_metadata = (
        payload.filter(pl.col("_metadata_exists").is_null())
        .select(pl.len())
        .collect()
        .item()
    )
    if missing_metadata:
        raise ValueError(f"{missing_metadata:,} embeddable chunks have no metadata row")
    payload = payload.drop("_metadata_exists")

    raw_ids = (
        pl.scan_parquet(args.chunks, glob=False)
        .filter(pl.col("chunk_type") == "raw_table")
        .select(pl.col("chunk_id").alias("_raw_table_id"))
        .with_columns(pl.lit(True).alias("_raw_exists"))
    )
    payload = payload.join(
        raw_ids,
        left_on="raw_table_id",
        right_on="_raw_table_id",
        how="left",
    ).with_columns(
        pl.when((pl.col("chunk_type") == "table_summary") & pl.col("_raw_exists").is_null())
        .then(pl.lit("missing_raw_table"))
        .otherwise(pl.lit("ok"))
        .alias("expansion_status")
    ).drop("_raw_exists")

    if not args.keep_existing_context:
        payload = payload.with_columns(build_contextual_text_expr())

    # Hash joins may emit rows in a different order across machines. Stable ordering is
    # required because member assignment is based on global shard indexes.
    payload = payload.sort("chunk_id")
    payload.sink_parquet(output_path, compression="zstd")

    stats = (
        pl.scan_parquet(output_path, glob=False)
        .select(
            pl.len().alias("rows"),
            pl.col("chunk_id").n_unique().alias("unique_chunk_ids"),
            pl.col("doc_id").n_unique().alias("documents"),
            (pl.col("chunk_type") == "raw_table").sum().alias("raw_tables"),
            (pl.col("expansion_status") == "missing_raw_table").sum().alias("missing_raw_tables"),
            (
                (pl.col("chunk_type") == "table_summary")
                & (
                    (pl.col("answer_source") != "raw_table")
                    | (~pl.col("do_not_answer_from_summary"))
                )
            ).sum().alias("invalid_table_summary_rules"),
            pl.col("contextual_text").is_null().sum().alias("null_contexts"),
        )
        .collect()
        .row(0, named=True)
    )
    if stats["rows"] != stats["unique_chunk_ids"]:
        raise ValueError("chunk_id is not unique in the frozen embedding payload")
    if stats["raw_tables"] or stats["null_contexts"] or stats["invalid_table_summary_rules"]:
        raise ValueError(f"Embedding payload invariant failed: {stats}")
    (
        pl.scan_parquet(output_path, glob=False)
        .filter(pl.col("expansion_status") == "missing_raw_table")
        .select("chunk_id", "doc_id", "chunk_type", "raw_table_id", "table_id", "summary_of")
        .sink_parquet(args.output_dir / "table_repair_candidates.parquet", compression="zstd")
    )

    atomic_write_json(
        args.output_dir / "prepare_manifest.json",
        {
            "version": args.version,
            "chunker_version": args.chunker_version,
            "chunks_fingerprint": file_fingerprint(args.chunks),
            "metadata_fingerprint": file_fingerprint(args.metadata),
            "output": str(output_path),
            "stats": stats,
        },
    )
    logging.info("Wrote %s with %s rows", output_path, f"{stats['rows']:,}")


if __name__ == "__main__":
    main()
