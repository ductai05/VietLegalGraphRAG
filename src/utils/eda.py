"""
eda.py – Shared utility functions for Vietnamese Legal Document EDA.
RAM-optimized: avoids loading full text columns into memory.
"""

import os
import polars as pl
import numpy as np


# ══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _try_numeric_cast(series: pl.Series) -> pl.Series | None:
    """Try to cast a series to Int64. Return None if it fails."""
    try:
        return series.cast(pl.Int64)
    except Exception:
        return None


def get_parquet_schema(path: str) -> pl.DataFrame:
    """Return schema as a DataFrame: [column, dtype]."""
    schema = pl.scan_parquet(path).collect_schema()
    return pl.DataFrame([
        {"column": col, "dtype": str(dtype)}
        for col, dtype in schema.items()
    ])


# ══════════════════════════════════════════════════════════════════════════
#  COLUMN STATS & LABELS (RAM-safe: processes column-by-column)
# ══════════════════════════════════════════════════════════════════════════

def compute_column_stats(path: str) -> pl.DataFrame:
    """
    Thống kê từng cột – RAM-safe: chỉ load từng cột riêng lẻ.
    """
    schema = pl.scan_parquet(path).collect_schema()
    total = pl.scan_parquet(path).select(pl.len()).collect().item()
    rows = []

    for col, dtype in schema.items():
        # Load only this column
        s = pl.scan_parquet(path).select(pl.col(col)).collect().to_series()
        null_count = s.null_count()
        n_unique = s.n_unique()

        row = {
            "column": col,
            "dtype": str(dtype),
            "n_unique": n_unique,
            "null_count": null_count,
            "null_%": round(null_count / total * 100, 1) if total > 0 else 0.0,
            "detail": "",
        }

        if null_count >= total:
            row["detail"] = "ALL NULL"
            rows.append(row)
            continue

        # Numeric
        if dtype.is_numeric():
            non_null = s.drop_nulls()
            row["detail"] = f"range=[{non_null.min()}, {non_null.max()}]"
            rows.append(row)
            del non_null
            continue

        # String – compute stats lazily where possible
        if dtype == pl.String:
            lengths = s.drop_nulls().str.len_chars()
            avg_l = round(lengths.mean(), 0)
            max_l = lengths.max()
            del lengths  # free memory
            top = s.value_counts(sort=True).head(1).to_dicts()
            top_str = ""
            if top:
                tv = str(top[0][col])[:40]
                tc = top[0]["count"]
                top_str = f' | top: "{tv}" ({tc:,}x)'
            row["detail"] = f"len: avg={avg_l:.0f}, max={max_l}{top_str}"
            rows.append(row)
            del s  # free memory
            continue

        # Other
        try:
            non_null = s.drop_nulls()
            row["detail"] = f"range=[{non_null.min()}, {non_null.max()}]"
            del non_null
        except Exception:
            row["detail"] = "N/A"
        rows.append(row)
        del s

    return pl.DataFrame(rows)


def get_label_value_counts(
    path: str,
    max_unique: int = 50,
) -> dict[str, pl.DataFrame]:
    """Trả dict {column: DataFrame[value, count, pct]} cho cột categorical.
    RAM-safe: chỉ load từng cột riêng lẻ."""
    schema = pl.scan_parquet(path).collect_schema()
    total = pl.scan_parquet(path).select(pl.len()).collect().item()
    result = {}

    for col, dtype in schema.items():
        # Only process string columns
        if dtype != pl.String:
            continue
        # Quick check n_unique via lazy
        n_unique = (
            pl.scan_parquet(path)
            .select(pl.col(col).n_unique())
            .collect().item()
        )
        if n_unique <= max_unique:
            vc = (
                pl.scan_parquet(path)
                .group_by(col)
                .agg(pl.len().alias("count"))
                .sort("count", descending=True)
                .with_columns(
                    (pl.col("count") / total * 100).round(2).alias("pct(%)")
                )
                .collect()
            )
            result[col] = vc
    return result


# ══════════════════════════════════════════════════════════════════════════
#  COMPARISON & RELATIONSHIP ANALYSIS (RAM-optimized)
# ══════════════════════════════════════════════════════════════════════════

def compare_content_datasets(
    data_path: str,
    legacy_path: str,
) -> dict:
    """
    So sánh data/content vs legacy/content.
    RAM-safe: KHÔNG load cột content/content_html vào bộ nhớ.
    Chỉ tính string length qua Polars lazy, rồi trả histogram bins.
    """
    # Schema
    sd = pl.scan_parquet(data_path).collect_schema()
    sl = pl.scan_parquet(legacy_path).collect_schema()

    # Row counts (lazy – no memory)
    n_data = pl.scan_parquet(data_path).select(pl.len()).collect().item()
    n_legacy = pl.scan_parquet(legacy_path).select(pl.len()).collect().item()

    # Load ONLY IDs (Int64 – tiny memory footprint)
    ids_data_raw = pl.scan_parquet(data_path).select("id").collect().to_series()
    try:
        ids_data = set(ids_data_raw.cast(pl.Int64).to_list())
    except Exception:
        ids_data = set(ids_data_raw.to_list())
    del ids_data_raw

    ids_legacy_raw = pl.scan_parquet(legacy_path).select("id").collect().to_series()
    numeric = _try_numeric_cast(ids_legacy_raw)
    if numeric is not None:
        ids_legacy = set(numeric.to_list())
        del numeric
    else:
        ids_legacy = set(ids_legacy_raw.cast(pl.Int64).to_list())
    del ids_legacy_raw

    set_data = ids_data
    set_legacy = ids_legacy
    overlap = set_data & set_legacy
    only_data = set_data - set_legacy
    only_legacy = set_legacy - set_data

    # Content column names
    content_col_data = "content_html" if "content_html" in sd.names() else "content"
    content_col_legacy = "content" if "content" in sl.names() else "content_html"

    # Content length stats – compute lazily, NEVER load text into RAM
    # Only load the integer length column
    len_data = (
        pl.scan_parquet(data_path)
        .select(pl.col(content_col_data).str.len_chars().alias("len"))
        .collect()
        .to_series()
    )
    len_legacy = (
        pl.scan_parquet(legacy_path)
        .select(pl.col(content_col_legacy).str.len_chars().alias("len"))
        .collect()
        .to_series()
    )

    # Pre-compute histogram data to avoid passing huge arrays to matplotlib
    CLIP_MAX = 200_000
    bins = np.linspace(0, CLIP_MAX, 81)

    len_d_np = len_data.clip(0, CLIP_MAX).to_numpy()
    hist_data, _ = np.histogram(len_d_np, bins=bins)
    del len_d_np

    len_l_np = len_legacy.clip(0, CLIP_MAX).to_numpy()
    hist_legacy, _ = np.histogram(len_l_np, bins=bins)
    del len_l_np

    # Compute summary stats before freeing
    median_data = float(len_data.median())
    median_legacy = float(len_legacy.median())

    del len_data, len_legacy  # free ~500k+ int arrays

    return {
        "schema_data": dict(sd),
        "schema_legacy": dict(sl),
        "n_data": n_data,
        "n_legacy": n_legacy,
        "n_overlap": len(overlap),
        "n_only_data": len(only_data),
        "n_only_legacy": len(only_legacy),
        "content_col_data": content_col_data,
        "content_col_legacy": content_col_legacy,
        # Pre-computed histogram instead of raw arrays
        "hist_data": hist_data,
        "hist_legacy": hist_legacy,
        "hist_bins": bins,
        "median_data": median_data,
        "median_legacy": median_legacy,
    }


def compare_metadata_datasets(
    data_path: str,
    legacy_path: str,
) -> dict:
    """
    So sánh data/metadata vs legacy/metadata.
    """
    sd = pl.scan_parquet(data_path).collect_schema()
    sl = pl.scan_parquet(legacy_path).collect_schema()

    n_data = pl.scan_parquet(data_path).select(pl.len()).collect().item()
    n_legacy = pl.scan_parquet(legacy_path).select(pl.len()).collect().item()

    # Column mapping: data (Vietnamese) → legacy (English)
    col_map = {
        "so_ky_hieu": "document_number",
        "title": "title",
        "loai_van_ban": "legal_type",
        "co_quan_ban_hanh": "issuing_authority",
        "ngay_ban_hanh": "issuance_date",
        "ngay_co_hieu_luc": "effect_date",
        "ngay_het_hieu_luc": "effectless_date",
        "tinh_trang_hieu_luc": "effect_status",
        "nguoi_ky": "signers",
    }

    # Columns only in one dataset
    data_only_cols = [c for c in sd.names() if c != "id" and c not in col_map]
    legacy_only_cols = [c for c in sl.names() if c != "id" and c not in col_map.values()]

    # ID overlap – only load ID column (Int64, small)
    ids_data = set(
        pl.scan_parquet(data_path)
        .select(pl.col("id").cast(pl.Int64))
        .collect().to_series().to_list()
    )
    ids_legacy = set(
        pl.scan_parquet(legacy_path)
        .select(pl.col("id").cast(pl.Int64))
        .collect().to_series().to_list()
    )
    overlap = ids_data & ids_legacy

    # Compare categorical columns – lazy, only load the single column
    cat_comparisons = {}
    cat_pairs = [
        ("loai_van_ban", "legal_type"),
        ("tinh_trang_hieu_luc", "effect_status"),
    ]
    for data_col, legacy_col in cat_pairs:
        if data_col in sd.names() and legacy_col in sl.names():
            vc_data = (
                pl.scan_parquet(data_path)
                .select(pl.col(data_col))
                .collect().to_series()
                .drop_nulls().value_counts(sort=True)
                .rename({data_col: "value"})
            )
            vc_legacy = (
                pl.scan_parquet(legacy_path)
                .select(pl.col(legacy_col))
                .collect().to_series()
                .drop_nulls().value_counts(sort=True)
                .rename({legacy_col: "value"})
            )
            cat_comparisons[f"{data_col} vs {legacy_col}"] = {
                "data": vc_data,
                "legacy": vc_legacy,
            }

    return {
        "n_data": n_data,
        "n_legacy": n_legacy,
        "schema_data": list(sd.names()),
        "schema_legacy": list(sl.names()),
        "col_map": col_map,
        "data_only_cols": data_only_cols,
        "legacy_only_cols": legacy_only_cols,
        "n_overlap": len(overlap),
        "n_only_data": len(ids_data - ids_legacy),
        "n_only_legacy": len(ids_legacy - ids_data),
        "cat_comparisons": cat_comparisons,
    }


def get_id_coverage(
    content_path: str,
    metadata_path: str,
    rel_path: str,
) -> dict:
    """
    Phân tích mối quan hệ ID giữa 3 bảng: content, metadata, relationships.
    RAM-safe: chỉ load cột ID (Int64).
    """
    ids_content_raw = (
        pl.scan_parquet(content_path)
        .select(pl.col("id"))
        .collect()
        .to_series()
    )
    try:
        ids_content = set(ids_content_raw.cast(pl.Int64).to_list())
    except Exception:
        ids_content = set(ids_content_raw.to_list())
    del ids_content_raw

    ids_metadata = set(
        pl.scan_parquet(metadata_path)
        .select(pl.col("id").cast(pl.Int64))
        .collect()
        .to_series()
        .to_list()
    )

    # Relationships: only load doc_id and other_doc_id (two Int64 columns)
    rels = (
        pl.scan_parquet(rel_path)
        .select(
            pl.col("doc_id").cast(pl.Int64),
            pl.col("other_doc_id").cast(pl.Int64),
        )
        .collect()
    )
    ids_rel_src = set(rels["doc_id"].to_list())
    ids_rel_tgt = set(rels["other_doc_id"].to_list())
    ids_rel_all = ids_rel_src | ids_rel_tgt

    return {
        "n_content": len(ids_content),
        "n_metadata": len(ids_metadata),
        "n_rel_rows": len(rels),
        "n_rel_unique_docs": len(ids_rel_all),
        "content_in_metadata": len(ids_content & ids_metadata),
        "content_not_in_metadata": len(ids_content - ids_metadata),
        "metadata_not_in_content": len(ids_metadata - ids_content),
        "rel_src_in_metadata": len(ids_rel_src & ids_metadata),
        "rel_src_not_in_metadata": len(ids_rel_src - ids_metadata),
        "rel_tgt_in_metadata": len(ids_rel_tgt & ids_metadata),
        "rel_tgt_not_in_metadata": len(ids_rel_tgt - ids_metadata),
        "ids_content": ids_content,
        "ids_metadata": ids_metadata,
        "ids_rel_all": ids_rel_all,
    }


# ══════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT (optional)
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    BASE = os.path.dirname(__file__) or "."
    FILES = [
        os.path.join(BASE, "data", "content.parquet"),
        os.path.join(BASE, "data", "metadata.parquet"),
        os.path.join(BASE, "data", "relationships.parquet"),
        os.path.join(BASE, "legacy", "content.parquet"),
        os.path.join(BASE, "legacy", "metadata.parquet"),
    ]
    for f in FILES:
        if os.path.exists(f):
            print(f"\n{'='*60}")
            print(f"  {f}")
            print(f"{'='*60}")
            print(compute_column_stats(f))
