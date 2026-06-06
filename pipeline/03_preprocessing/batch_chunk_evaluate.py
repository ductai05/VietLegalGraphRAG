# -*- coding: utf-8 -*-
"""
Đánh giá chất lượng dataset chunking trên Kaggle (memory-safe).

Input:
  - .../legal_chunking_dataset/{chunks,metadata}.parquet
  - .../content.parquet (chỉ cột id + độ dài cho Coverage)

Metrics: pipeline/03_preprocessing/README_CHUNKING.md §5.1 (corpus + dense index)
Biểu đồ hiển thị inline trên Kaggle (plt.show); cache nội bộ metrics_narrow.parquet tránh OOM.
"""

# =============================================================================
# CELL 1 — Cấu hình, import, lazy scan
# =============================================================================

import gc
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd
import polars as pl
import seaborn as sns
from matplotlib.gridspec import GridSpec

BASE_DATASET = Path(
    "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned"
)
CHUNKING_DATASET_DIR = BASE_DATASET / "legal_chunking_dataset"
CHUNKS_PATH = CHUNKING_DATASET_DIR / "chunks.parquet"
METADATA_PATH = CHUNKING_DATASET_DIR / "metadata.parquet"
CONTENT_PATH = BASE_DATASET / "content.parquet"

# Fallback: Kaggle có thể mount cùng file ở slug khác hoặc dataset chỉ chứa legal_chunking_dataset/
_CONTENT_FALLBACKS = [
    BASE_DATASET / "content.parquet",
    Path("/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/content.parquet"),
    Path("/kaggle/input/vietnamese-legal-documents-cleaned/content.parquet"),
]


def resolve_content_path() -> Optional[Path]:
    for p in _CONTENT_FALLBACKS:
        if p.is_file():
            return p
    # Quét toàn bộ /kaggle/input — tránh coverage=0 im lặng khi path mount khác tên
    kaggle_input = Path("/kaggle/input")
    if kaggle_input.is_dir():
        hits = sorted(kaggle_input.rglob("content.parquet"))
        if len(hits) == 1:
            return hits[0]
        # Ưu tiên file có cột `content` (không phải merged_content / legacy-only)
        for hit in hits:
            try:
                names = pl.scan_parquet(hit).collect_schema().names()
                if "content" in names and "id" in names:
                    return hit
            except Exception:
                continue
    return None


WORK_DIR = Path("/kaggle/working/chunk_eval")
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Hiển thị biểu đồ inline trên Kaggle Notebook
try:
    get_ipython().run_line_magic("matplotlib", "inline")
except NameError:
    pass

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

THRESHOLDS = {
    "coverage_min": 0.95,
    "coverage_target": 0.998,
    "tiny_pct_max": 5.0,
    "oversized_3k_pct_max": 2.0,
    "hard_split_count_max": 100,
    "orphan_pct_max": 0.0,
    "metadata_propagation_min": 100.0,
    "boundary_violations_max": 0,
    "table_integrity_bad_pct_max": 10.0,
    # Chỉ áp dụng trên chunk embed=True (dense index) — khớp legal_chunker._emit_chunk
    "dense_oversized_3k_pct_max": 2.0,
    "dense_hard_split_count_max": 100,
    "dense_tiny_pct_max": 5.0,
}
TINY_CHAR_LIMIT = 50
OVERSIZE_SOFT = 2000
OVERSIZE_HARD = 3000
# Chunk types được phép > hard_max_chars hoặc không đưa vào dense index
OVERSIZE_EXEMPT_TYPES = frozenset({"raw_table"})
NON_EMBED_TYPES = frozenset({"raw_table", "signature", "distribution_list"})
STRATIFIED_SAMPLE_N = 100
RANDOM_SEED = 42
VIZ_SAMPLE_ROWS = 250_000
BOUNDARY_MAX_DOCS = 3_000
LARGE_CHUNK_THRESHOLD = 10_000

sns.set_theme(style="whitegrid", context="notebook", font_scale=1.05)
plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 150})
PALETTE_MAIN = sns.color_palette("husl", 12)
PALETTE_GRAD = sns.color_palette("rocket", as_cmap=True)
PALETTE_COOL = sns.color_palette("viridis", as_cmap=True)
PALETTE_WARM = sns.color_palette("flare", as_cmap=True)

_RE_BOUNDARY_HEAD_DIEU = re.compile(r"^\s*Điều\s+\d+", re.IGNORECASE)
_RE_BOUNDARY_PREV_ENDS_WITH_DIEU_HEADER_ONLY = re.compile(
    r"(?:^|\n)\s*Điều\s+\d+\s*[:.]?\s*$",
    re.IGNORECASE,
)
_RE_TABLE_HEADER_HINT = re.compile(
    r"(STT|TT|Mã|Tên|Nội dung|Thủ tục|Đơn vị|Ghi chú|Thời hạn)",
    re.IGNORECASE,
)

assert CHUNKING_DATASET_DIR.is_dir()
assert CHUNKS_PATH.is_file() and METADATA_PATH.is_file()

meta_pl = pl.read_parquet(METADATA_PATH)
meta_doc_ids = meta_pl.select(pl.col("id").alias("doc_id")).unique()
meta_doc_ids_lf = meta_doc_ids.lazy()

chunks_lf = pl.scan_parquet(CHUNKS_PATH).with_row_index("_emit_order")
_schema = chunks_lf.collect_schema().names()
HAS_FLAGS_LIST = "quality_flags" in _schema
HAS_SECTION_LIST = "section_path" in _schema
HAS_EMBED_COL = "embed" in _schema
HAS_KEYWORD_COL = "keyword_index" in _schema
HAS_RAW_TABLE_ID = "raw_table_id" in _schema
HAS_TABLE_COLUMNS = "table_columns" in _schema
HAS_ANSWER_SOURCE = "answer_source" in _schema
HAS_NO_ANSWER_SUMMARY = "do_not_answer_from_summary" in _schema

_row_count = chunks_lf.select(pl.len()).collect().item()
_doc_count = chunks_lf.select(pl.col("doc_id").n_unique()).collect().item()
print(f"Chunks: {_row_count:,} rows | {_doc_count:,} docs | metadata: {meta_pl.height:,}")


# =============================================================================
# CELL 2 — Metrics LazyFrame (không giữ chunk_text)
# =============================================================================


def _flag_contains(flag: str) -> pl.Expr:
    if HAS_FLAGS_LIST:
        return pl.col("quality_flags").list.contains(flag)
    return pl.col("quality_flags_json").str.contains(flag)


def build_metrics_lf() -> pl.LazyFrame:
    cols = ["doc_id", "chunk_id", "chunk_type", "_emit_order"]
    if HAS_SECTION_LIST:
        cols.append("section_path")
    if HAS_FLAGS_LIST:
        cols.append("quality_flags")
    else:
        cols.append("quality_flags_json")
    if HAS_EMBED_COL:
        cols.append("embed")
    if HAS_KEYWORD_COL:
        cols.append("keyword_index")

    lf = chunks_lf.select(
        *cols,
        pl.col("chunk_text").str.len_chars().alias("char_len"),
    )
    if HAS_SECTION_LIST:
        lf = lf.with_columns(pl.col("section_path").list.len().alias("section_path_len"))
    else:
        lf = lf.with_columns(pl.lit(0).cast(pl.UInt32).alias("section_path_len"))

    if HAS_EMBED_COL:
        lf = lf.with_columns(pl.col("embed").fill_null(True).alias("is_embeddable"))
    else:
        lf = lf.with_columns(
            (~pl.col("chunk_type").is_in(list(NON_EMBED_TYPES))).alias("is_embeddable")
        )
    if HAS_KEYWORD_COL:
        lf = lf.with_columns(pl.col("keyword_index").fill_null(True).alias("is_keyword_indexable"))
    else:
        lf = lf.with_columns(
            (~pl.col("chunk_type").is_in(["signature", "distribution_list"])).alias("is_keyword_indexable")
        )

    lf = lf.with_columns(
        _flag_contains("tiny_chunk").alias("has_tiny_flag"),
        _flag_contains("oversized_chunk").alias("has_oversized_flag"),
        _flag_contains("hard_char_split").alias("has_hard_split"),
        (pl.col("char_len") < TINY_CHAR_LIMIT).alias("is_tiny_metric"),
        (pl.col("char_len") > OVERSIZE_SOFT).alias("is_oversized_2k"),
        (pl.col("char_len") > OVERSIZE_HARD).alias("is_oversized_3k"),
        (
            pl.col("is_embeddable")
            & (pl.col("char_len") > OVERSIZE_HARD)
            & (~pl.col("chunk_type").is_in(list(OVERSIZE_EXEMPT_TYPES)))
        ).alias("is_oversized_3k_dense"),
        (
            pl.col("is_embeddable")
            & (pl.col("char_len") < TINY_CHAR_LIMIT)
        ).alias("is_tiny_dense"),
    ).with_columns(
        (pl.col("is_embeddable") & pl.col("has_hard_split")).alias("is_hard_split_dense"),
    ).join(
        meta_doc_ids_lf.with_columns(pl.lit(True).alias("_in_meta")),
        on="doc_id",
        how="left",
    ).with_columns(
        ((pl.col("section_path_len") == 0) | pl.col("_in_meta").is_null()).alias("is_orphan")
    ).drop("_in_meta")

    drop_cols = [
        c for c in (
            "quality_flags", "quality_flags_json", "section_path",
            "embed", "keyword_index",
        )
        if c in cols
    ]
    return lf.drop(drop_cols) if drop_cols else lf


METRICS_CACHE = WORK_DIR / "metrics_narrow_v2.parquet"
if METRICS_CACHE.exists():
    metrics_lf = pl.scan_parquet(METRICS_CACHE)
    print(f"Dùng cache metrics: {METRICS_CACHE}")
else:
    print("Materialize metrics (một lần đọc chunk_text) → cache parquet...")
    build_metrics_lf().collect(engine="streaming").write_parquet(METRICS_CACHE, compression="zstd")
    metrics_lf = pl.scan_parquet(METRICS_CACHE)
    gc.collect()
    print(f"Đã ghi cache: {METRICS_CACHE}")


def collect_global_metrics(lf: pl.LazyFrame) -> Dict[str, Any]:
    summary = lf.select(
        pl.len().alias("n_chunks"),
        pl.col("doc_id").n_unique().alias("n_docs"),
        (pl.col("is_tiny_metric").mean() * 100).alias("tiny_pct_lt50chars"),
        (pl.col("has_tiny_flag").mean() * 100).alias("tiny_flag_pct"),
        (pl.col("is_oversized_2k").mean() * 100).alias("oversized_2k_pct"),
        (pl.col("is_oversized_3k").mean() * 100).alias("oversized_3k_pct"),
        (pl.col("has_oversized_flag").mean() * 100).alias("oversized_flag_pct"),
        pl.col("has_hard_split").sum().alias("hard_split_count"),
        pl.col("is_orphan").sum().alias("orphan_count"),
        (pl.col("is_orphan").mean() * 100).alias("orphan_pct"),
        pl.col("is_embeddable").sum().alias("embed_chunk_count"),
        (pl.col("is_embeddable").mean() * 100).alias("embed_chunk_pct"),
        pl.col("is_keyword_indexable").sum().alias("keyword_chunk_count"),
        (pl.col("is_keyword_indexable").mean() * 100).alias("keyword_chunk_pct"),
        (pl.col("is_tiny_dense").mean() * 100).alias("dense_tiny_pct_lt50chars"),
        (pl.col("is_oversized_3k_dense").mean() * 100).alias("dense_oversized_3k_pct"),
        pl.col("is_hard_split_dense").sum().alias("dense_hard_split_count"),
    ).collect(engine="streaming").row(0, named=True)

    n_docs = summary["n_docs"] or 1
    docs_with_meta = (
        lf.join(meta_doc_ids_lf, on="doc_id", how="inner")
        .select(pl.col("doc_id").n_unique())
        .collect(engine="streaming")
        .item()
    )
    summary["metadata_propagation_pct"] = 100.0 * docs_with_meta / n_docs

    flag_sums = lf.select(
        pl.col("has_tiny_flag").sum().alias("tiny_chunk"),
        pl.col("has_oversized_flag").sum().alias("oversized_chunk"),
        pl.col("has_hard_split").sum().alias("hard_char_split"),
    ).collect(engine="streaming").row(0, named=True)
    summary["quality_flag_counts"] = {k: int(v) for k, v in flag_sums.items()}

    type_df = (
        lf.group_by("chunk_type")
        .len()
        .sort("len", descending=True)
        .collect(engine="streaming")
    )
    summary["chunk_type_counts"] = dict(
        zip(type_df["chunk_type"].to_list(), type_df["len"].to_list())
    )
    return summary


metrics = collect_global_metrics(metrics_lf)
# Gán sau CELL 5/6; None để dashboard/report không KeyError khi chạy lẻ từng cell
metrics.setdefault("boundary_violations", None)
metrics.setdefault("boundary_sample_docs", None)
metrics.setdefault("table_integrity_bad_pct", None)
metrics.setdefault("table_integrity_issues", None)

raw_table_ids_lf = (
    chunks_lf.filter(pl.col("chunk_type") == "raw_table")
    .select(pl.col("chunk_id").alias("_raw_table_id"))
    .with_columns(pl.lit(True).alias("_raw_exists"))
)
table_summary_lf = chunks_lf.filter(pl.col("chunk_type") == "table_summary")
if HAS_RAW_TABLE_ID:
    summary_link_stats = (
        table_summary_lf.select("raw_table_id")
        .join(raw_table_ids_lf, left_on="raw_table_id", right_on="_raw_table_id", how="left")
        .select(
            pl.len().alias("n"),
            pl.col("_raw_exists").fill_null(False).sum().alias("valid"),
        )
        .collect(engine="streaming")
        .row(0, named=True)
    )
    metrics["table_summary_has_raw_table_link_pct"] = (
        100.0 * summary_link_stats["valid"] / max(summary_link_stats["n"], 1)
    )
else:
    metrics["table_summary_has_raw_table_link_pct"] = 0.0

flag_stats = chunks_lf.select(
    (
        (~pl.col("embed")).filter(pl.col("chunk_type") == "raw_table").mean() * 100
    ).alias("raw_table_embed_false_pct"),
    (
        pl.col("embed").filter(pl.col("chunk_type") == "table_summary").mean() * 100
    ).alias("table_summary_embed_true_pct"),
).collect(engine="streaming").row(0, named=True)
metrics.update(flag_stats)

if HAS_TABLE_COLUMNS:
    proc_column_stats = chunks_lf.filter(
        pl.col("chunk_type") == "procedure_record"
    ).select(
        pl.len().alias("n"),
        (pl.col("table_columns").list.len() > 0).sum().alias("valid"),
    ).collect(engine="streaming").row(0, named=True)
    metrics["procedure_record_has_column_names_pct"] = (
        100.0 * proc_column_stats["valid"] / max(proc_column_stats["n"], 1)
    )
else:
    metrics["procedure_record_has_column_names_pct"] = 0.0
if HAS_ANSWER_SOURCE and HAS_NO_ANSWER_SUMMARY:
    answer_rule = table_summary_lf.select(
        pl.len().alias("n"),
        (
            (pl.col("answer_source") == "raw_table")
            & pl.col("do_not_answer_from_summary")
        ).sum().alias("valid"),
    ).collect(engine="streaming").row(0, named=True)
    metrics["table_summary_answer_rule_pct"] = (
        100.0 * answer_rule["valid"] / max(answer_rule["n"], 1)
    )
else:
    metrics["table_summary_answer_rule_pct"] = 0.0
gc.collect()


def stratified_doc_ids(n_docs: int = STRATIFIED_SAMPLE_N) -> List[int]:
    content_path = resolve_content_path()
    if content_path is None:
        u = metrics_lf.select("doc_id").unique().collect(engine="streaming")
        return u.sample(n=min(n_docs, u.height), seed=RANDOM_SEED)["doc_id"].to_list()
    lens = (
        pl.scan_parquet(content_path)
        .select(pl.col("id"), pl.col("content").str.len_chars().alias("content_len"))
        .collect()
    )
    pdf = lens.to_pandas()
    pdf["stratum"] = pd.qcut(
        pdf["content_len"],
        q=min(10, max(2, n_docs // 10)),
        duplicates="drop",
    )
    rng = np.random.default_rng(RANDOM_SEED)
    ids: List[int] = []
    per = max(1, n_docs // pdf["stratum"].nunique())
    for _, grp in pdf.groupby("stratum", observed=True):
        pool = grp["id"].tolist()
        rng.shuffle(pool)
        ids.extend(pool[:per])
    return list(dict.fromkeys(ids))[:n_docs]


sample_doc_ids = stratified_doc_ids()
print(f"Stratified / sample doc_ids: {len(sample_doc_ids)}")


# =============================================================================
# CELL 3 — Coverage (Polars, không load full content text vào RAM lâu)
# =============================================================================


def compute_coverage_df() -> Tuple[pd.DataFrame, str]:
    chunk_sum = (
        metrics_lf.group_by("doc_id")
        .agg(
            pl.col("char_len").sum().alias("chunk_chars_sum"),
            pl.col("char_len").filter(pl.col("is_embeddable")).sum().alias("dense_chars_sum"),
        )
        .collect(engine="streaming")
    )
    n_chunk_docs = chunk_sum.height

    content_path = resolve_content_path()
    if content_path is None:
        return pd.DataFrame(), (
            "SKIP: không tìm thấy content.parquet (cần cột id + content). "
            f"Đã thử: {CONTENT_PATH}. "
            "→ Thêm dataset gốc `vietnamese-legal-documents-cleaned` vào notebook "
            "(Add Data), không chỉ thư mục legal_chunking_dataset."
        )

    schema = pl.scan_parquet(content_path).collect_schema().names()
    if "content" not in schema:
        return pd.DataFrame(), (
            f"SKIP: {content_path} thiếu cột `content` (có: {schema}). "
            "Coverage cần file content.parquet đã preprocess, không phải content_html."
        )

    id_col = "id"
    content_lens = (
        pl.scan_parquet(content_path)
        .select(
            pl.col(id_col).cast(pl.Int64).alias("doc_id"),
            pl.col("content").str.len_chars().alias("content_len"),
        )
        .collect(engine="streaming")
    )
    n_content_docs = content_lens.height

    merged = chunk_sum.with_columns(pl.col("doc_id").cast(pl.Int64)).join(
        content_lens, on="doc_id", how="inner"
    )
    n_matched = merged.height
    if n_matched == 0:
        sample_chunk = chunk_sum["doc_id"].head(5).to_list()
        sample_content = content_lens["doc_id"].head(5).to_list()
        return pd.DataFrame(), (
            f"SKIP: inner join doc_id trả về 0 hàng "
            f"(chunk docs={n_chunk_docs:,}, content docs={n_content_docs:,}). "
            f"Ví dụ doc_id chunk={sample_chunk}, content={sample_content}. "
            "Có thể chunks và content.parquet không cùng một pipeline/version."
        )

    merged = merged.with_columns(
        (pl.col("chunk_chars_sum") / pl.col("content_len").clip(lower_bound=1)).alias("coverage"),
        (pl.col("dense_chars_sum") / pl.col("content_len").clip(lower_bound=1)).alias("dense_coverage"),
    )
    status = (
        f"OK: {n_matched:,}/{n_chunk_docs:,} docs khớp content "
        f"(content: {content_path})"
    )
    return merged.to_pandas(), status


coverage_df, coverage_status = compute_coverage_df()
print(f"\nCoverage: {coverage_status}")
if len(coverage_df):
    metrics["coverage_mean"] = float(coverage_df["coverage"].mean())
    metrics["coverage_median"] = float(coverage_df["coverage"].median())
    metrics["dense_coverage_mean"] = float(coverage_df["dense_coverage"].mean())
    metrics["coverage_docs_below_95pct"] = int(
        (coverage_df["coverage"] < THRESHOLDS["coverage_min"]).sum()
    )
else:
    metrics["coverage_mean"] = None
    metrics["coverage_median"] = None
    metrics["dense_coverage_mean"] = None
    metrics["coverage_docs_below_95pct"] = None

print("\n=== GLOBAL METRICS ===")
for k, v in metrics.items():
    if k not in ("quality_flag_counts", "chunk_type_counts"):
        print(f"  {k}: {v}")
gc.collect()


# =============================================================================
# CELL 4 — Visualization (sample nhỏ, không chunk_text)
# =============================================================================


def show_fig(*, use_tight: bool = True) -> None:
    """Hiển thị figure trực tiếp trong notebook (không ghi file)."""
    if use_tight:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            try:
                plt.tight_layout()
            except Exception:
                pass
    plt.show()


def load_viz_sample(max_rows: int = VIZ_SAMPLE_ROWS) -> pd.DataFrame:
    lf = metrics_lf.filter(pl.col("char_len") < 8000).select("char_len", "chunk_type")
    n = lf.select(pl.len()).collect(engine="streaming").item()
    if n > max_rows:
        return lf.collect(engine="streaming").sample(n=max_rows, seed=RANDOM_SEED).to_pandas()
    return lf.collect(engine="streaming").to_pandas()


viz_pd = load_viz_sample()
gc.collect()

fig, ax = plt.subplots(figsize=(12, 5))
top_types = viz_pd["chunk_type"].value_counts().head(8).index.tolist()
plot_df = viz_pd[viz_pd["chunk_type"].isin(top_types)]
n_types = len(top_types)
sns.histplot(
    data=plot_df, x="char_len", hue="chunk_type", multiple="stack",
    palette=sns.color_palette("husl", n_colors=n_types),
    bins=60, edgecolor="white", linewidth=0.3, ax=ax,
)
for x, c, lbl in [
    (TINY_CHAR_LIMIT, "#e74c3c", f"Tiny < {TINY_CHAR_LIMIT}"),
    (OVERSIZE_SOFT, "#f39c12", f"Soft {OVERSIZE_SOFT}"),
    (OVERSIZE_HARD, "#9b59b6", f"Hard {OVERSIZE_HARD}"),
]:
    ax.axvline(x, color=c, ls="--", lw=1.5, label=lbl)
ax.set_title(f"Phân phối kích thước (sample ≤{len(plot_df):,} rows)")
ax.legend(loc="upper right", fontsize=8)
show_fig()

order = (
    viz_pd.groupby("chunk_type")["char_len"].median()
    .sort_values(ascending=False).index.tolist()[:10]
)
sub = viz_pd[viz_pd["chunk_type"].isin(order)].copy()
sub["char_len_clip"] = sub["char_len"].clip(upper=6000)
fig, ax = plt.subplots(figsize=(11, 6))
sns.boxplot(
    data=sub, x="chunk_type", y="char_len_clip", order=order,
    palette=sns.color_palette("crest", n_colors=len(order)), ax=ax,
)
ax.tick_params(axis="x", labelrotation=35)
for lbl in ax.get_xticklabels():
    lbl.set_ha("right")
ax.set_title("Boxplot kích thước theo chunk_type (sample)")
show_fig()
del viz_pd, plot_df, sub
gc.collect()

if len(coverage_df):
    chunk_counts = (
        metrics_lf.group_by("doc_id")
        .len()
        .rename({"len": "n_chunks"})
        .collect(engine="streaming")
        .to_pandas()
    )
    scatter_df = coverage_df.merge(chunk_counts, on="doc_id", how="left")
    if len(scatter_df) > 50_000:
        scatter_df = scatter_df.sample(50_000, random_state=RANDOM_SEED)
    fig, ax = plt.subplots(figsize=(10, 7))
    sc = ax.scatter(
        scatter_df["content_len"], scatter_df["n_chunks"], c=scatter_df["coverage"],
        cmap=PALETTE_COOL, alpha=0.55, s=18, edgecolors="white", linewidths=0.2,
    )
    sns.regplot(
        data=scatter_df, x="content_len", y="n_chunks", scatter=False,
        color="#e84393", line_kws={"lw": 2, "alpha": 0.85}, ax=ax,
    )
    plt.colorbar(sc, ax=ax, label="Coverage")
    ax.set_xscale("symlog")
    ax.set_title("Số chunk vs độ dài gốc")
    show_fig()

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    sns.kdeplot(data=coverage_df, x="coverage", fill=True, cmap=PALETTE_WARM, clip=(0, 1.5), ax=axes[0])
    axes[0].axvline(THRESHOLDS["coverage_target"], color="#00b894", ls="--")
    axes[0].axvline(THRESHOLDS["coverage_min"], color="#d63031", ls="--")
    sns.violinplot(data=coverage_df, y="coverage", ax=axes[1])
    show_fig()

flag_by_type = (
    metrics_lf.filter(pl.col("is_embeddable"))
    .group_by("chunk_type")
    .agg(
        pl.col("has_tiny_flag").sum().alias("tiny_chunk"),
        pl.col("has_oversized_flag").sum().alias("oversized_chunk"),
        pl.col("has_hard_split").sum().alias("hard_char_split"),
    )
    .collect(engine="streaming")
    .to_pandas()
    .set_index("chunk_type")
)
if len(flag_by_type):
    top_ct = flag_by_type.sum(axis=1).nlargest(10).index
    fig, ax = plt.subplots(figsize=(10, 6))
    sns.heatmap(flag_by_type.loc[top_ct], annot=True, fmt=".0f", cmap=PALETTE_GRAD, ax=ax)
    ax.set_title("chunk_type x quality_flags (embed=True only)")
    show_fig()
gc.collect()


# =============================================================================
# CELL 5 — Boundary integrity (giới hạn số doc, đọc text theo doc)
# =============================================================================


def check_boundary_sample(doc_ids: List[int]) -> pd.DataFrame:
    violations = []
    prose_types = ["article", "clause_group", "appendix_text", "preamble", "fallback_text"]
    for doc_id in doc_ids:
        lf = chunks_lf.filter(pl.col("doc_id") == doc_id).sort("_emit_order")
        if HAS_EMBED_COL:
            lf = lf.filter(pl.col("embed") == True)  # noqa: E712
        else:
            lf = lf.filter(~pl.col("chunk_type").is_in(list(NON_EMBED_TYPES)))
        lf = lf.filter(pl.col("chunk_type").is_in(prose_types))
        rows = lf.select("chunk_id", "chunk_text").collect()
        if rows.height < 2:
            continue
        texts = rows["chunk_text"].to_list()
        cids = rows["chunk_id"].to_list()
        for i in range(len(texts) - 1):
            prev_text = (texts[i] or "").rstrip()
            next_text = (texts[i + 1] or "").lstrip()

            # Boundary integrity: "không cắt ngang Điều"
            # Vi phạm điển hình: chunk trước chỉ chứa header "Điều N:" (hoặc "Điều N")
            # nhưng phần nội dung của Điều lại nằm ở chunk sau (chunk sau KHÔNG bắt đầu bằng "Điều ...").
            tail = prev_text[-160:]
            head = next_text[:120]

            prev_ends_with_dieu_header = bool(_RE_BOUNDARY_PREV_ENDS_WITH_DIEU_HEADER_ONLY.search(tail))
            next_starts_with_new_dieu = bool(_RE_BOUNDARY_HEAD_DIEU.match(head))

            if prev_ends_with_dieu_header and (head.strip() != "") and (not next_starts_with_new_dieu):
                violations.append(
                    {
                        "doc_id": doc_id,
                        "chunk_id_prev": cids[i],
                        "chunk_id_next": cids[i + 1],
                    }
                )
    return pd.DataFrame(violations)


boundary_doc_ids = sample_doc_ids[:BOUNDARY_MAX_DOCS]
boundary_df = check_boundary_sample(boundary_doc_ids)
metrics["boundary_violations"] = len(boundary_df)
metrics["boundary_violation_docs"] = int(boundary_df["doc_id"].nunique()) if len(boundary_df) else 0
metrics["boundary_sample_docs"] = len(boundary_doc_ids)
print(f"\nBoundary violations: {len(boundary_df)} (trên {len(boundary_doc_ids)} docs mẫu)")
gc.collect()

if len(boundary_df) > 0:
    fig, ax = plt.subplots(figsize=(8, 4))
    top_boundary = boundary_df.head(500)
    sns.countplot(
        data=top_boundary,
        x="doc_id",
        color=sns.color_palette("YlOrRd", 1)[0],
        ax=ax,
    )
    ax.set_title("Boundary violations (sample docs)")
    show_fig()


# =============================================================================
# CELL 6 — Table integrity (chỉ chunk_type bảng)
# =============================================================================


def _has_table_body(text: str) -> bool:
    return "|" in text and text.count("|") >= 2


def _has_table_header(text: str) -> bool:
    if not _has_table_body(text):
        return False
    return bool(_RE_TABLE_HEADER_HINT.search("\n".join(text.splitlines()[:3])))


table_types = ["table", "table_part", "raw_table", "table_summary", "procedure_record"]
table_select = [
    "chunk_id", "doc_id", "chunk_type", "chunk_text", "contextual_text",
    "parent_id", "procedure_name",
]
if HAS_TABLE_COLUMNS:
    table_select.append("table_columns")
table_rows = chunks_lf.filter(
    pl.col("chunk_type").is_in(table_types)
).select(*table_select).collect(engine="streaming")

raw_header_by_id = {
    row["chunk_id"]: _has_table_header(row["chunk_text"] or "")
    for row in table_rows.iter_rows(named=True)
    if row["chunk_type"] == "raw_table"
}
table_issues = []
counts = {
    "raw_table_total": 0,
    "raw_table_valid": 0,
    "table_part_total": 0,
    "table_part_valid": 0,
    "procedure_record_total": 0,
    "procedure_record_valid": 0,
}
for row in table_rows.iter_rows(named=True):
    text = row["chunk_text"] or ""
    issue = None
    if row["chunk_type"] == "raw_table":
        counts["raw_table_total"] += 1
        valid = _has_table_header(text)
        counts["raw_table_valid"] += int(valid)
        issue = None if valid else "raw_table_missing_header"
    elif row["chunk_type"] in {"table", "table_part"}:
        counts["table_part_total"] += 1
        valid = _has_table_header(text) or raw_header_by_id.get(row["parent_id"], False)
        counts["table_part_valid"] += int(valid)
        issue = None if valid else "table_part_missing_header_and_parent_header"
    elif row["chunk_type"] == "procedure_record":
        counts["procedure_record_total"] += 1
        has_columns = bool(row.get("table_columns")) if HAS_TABLE_COLUMNS else False
        has_context = bool(row.get("procedure_name")) and (
            has_columns or "Thông tin bảng gốc:" in (row["contextual_text"] or "")
        )
        counts["procedure_record_valid"] += int(has_context)
        issue = None if has_context else "procedure_record_missing_column_context"

    if issue:
        table_issues.append({
            "chunk_id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "chunk_type": row["chunk_type"],
            "char_len": len(text),
            "issue": issue,
        })

table_issues_df = pd.DataFrame(table_issues)
integrity_total = (
    counts["raw_table_total"] + counts["table_part_total"] + counts["procedure_record_total"]
)
metrics["raw_table_has_header_pct"] = 100.0 * counts["raw_table_valid"] / max(counts["raw_table_total"], 1)
metrics["table_part_has_header_or_parent_header_pct"] = 100.0 * counts["table_part_valid"] / max(counts["table_part_total"], 1)
metrics["procedure_record_has_column_context_pct"] = 100.0 * counts["procedure_record_valid"] / max(counts["procedure_record_total"], 1)
metrics["table_integrity_bad_pct"] = 100.0 * len(table_issues_df) / max(integrity_total, 1)
metrics["table_integrity_issues"] = len(table_issues_df)
print(
    "Table integrity (true parser issues): "
    f"{metrics['table_integrity_bad_pct']:.2f}% ({len(table_issues_df)} / {integrity_total})"
)
print(
    f"  raw_table_has_header={metrics['raw_table_has_header_pct']:.2f}% | "
    f"table_part_has_header_or_parent_header={metrics['table_part_has_header_or_parent_header_pct']:.2f}% | "
    f"procedure_record_has_column_context={metrics['procedure_record_has_column_context_pct']:.2f}%"
)
del table_rows
gc.collect()

fig, ax = plt.subplots(figsize=(9, 5))
if len(table_issues_df):
    sns.scatterplot(
        data=table_issues_df, x="char_len", y="doc_id", hue="chunk_type",
        palette="Set2", alpha=0.75, ax=ax,
    )
else:
    ax.text(0.5, 0.5, "Không phát hiện table thiếu header", ha="center", va="center")
    ax.set_axis_off()
show_fig()

type_series = pd.Series(metrics["chunk_type_counts"]).sort_values(ascending=False).head(12)
fig, ax = plt.subplots(figsize=(8, 8))
ax.pie(
    type_series.values, labels=type_series.index, autopct="%1.1f%%",
    colors=sns.color_palette("Spectral", len(type_series)),
    pctdistance=0.8, wedgeprops=dict(width=0.45, edgecolor="white"),
)
ax.set_title("chunk_type (donut — top 12)")
show_fig()

corpus_metric_checks = [
    ("Coverage (mean)", metrics["coverage_mean"], THRESHOLDS["coverage_target"], "higher"),
    ("Orphan (%)", metrics["orphan_pct"], THRESHOLDS["orphan_pct_max"], "lower"),
    ("Metadata propagation (%)", metrics["metadata_propagation_pct"], THRESHOLDS["metadata_propagation_min"], "higher"),
    ("Boundary violations (sample)", metrics["boundary_violations"], THRESHOLDS["boundary_violations_max"], "lower"),
    ("Table integrity issues (%)", metrics["table_integrity_bad_pct"], THRESHOLDS["table_integrity_bad_pct_max"], "lower"),
]
dense_metric_checks = [
    ("Dense hard split (count)", metrics["dense_hard_split_count"], THRESHOLDS["dense_hard_split_count_max"], "lower"),
    ("Dense oversized >3k (%)", metrics["dense_oversized_3k_pct"], THRESHOLDS["dense_oversized_3k_pct_max"], "lower"),
    ("Dense tiny <50 chars (%)", metrics["dense_tiny_pct_lt50chars"], THRESHOLDS["dense_tiny_pct_max"], "lower"),
]
metric_checks = corpus_metric_checks + dense_metric_checks
fig = plt.figure(figsize=(11, 7), layout="constrained")
gs = GridSpec(len(metric_checks), 1, figure=fig, hspace=0.55)
for i, (label, val, thr, direction) in enumerate(metric_checks):
    ax = fig.add_subplot(gs[i])
    if val is None:
        ax.axis("off")
        na_msg = (
            "N/A (thiếu content.parquet)"
            if "Coverage" in label
            else "N/A (chạy CELL 5–6 trước)"
        )
        ax.text(0.5, 0.5, f"{label}\n{na_msg}", ha="center", va="center")
        continue
    ok = (val >= thr * 0.95) if direction == "higher" else (val <= thr)
    ratio = min(1.2, val / thr) if direction == "higher" and thr else min(1.2, val / max(thr, 1e-9))
    color = PALETTE_COOL(0.15 + 0.7 * min(ratio, 1.0)) if ok else PALETTE_WARM(0.55)
    ax.barh([0], [val], color=color, height=0.5)
    ax.axvline(thr, color="#2d3436", ls="--", lw=2)
    ax.set_title(f"{label}: {val:.4g}  [{'PASS' if ok else 'CHECK'}]", loc="left")
show_fig(use_tight=False)


# =============================================================================
# CELL 7 — Báo cáo
# =============================================================================


def pass_fail(val: Optional[float], thr: float, higher: bool) -> str:
    if val is None:
        return "N/A"
    return "PASS" if (val >= thr if higher else val <= thr) else "FAIL"


def _fmt_metric(val: Optional[float]) -> str:
    return "N/A" if val is None else f"{val:.4g}"


rows_report = [
    ("Coverage (mean)", metrics["coverage_mean"], THRESHOLDS["coverage_target"], True),
    ("Orphan (%)", metrics["orphan_pct"], THRESHOLDS["orphan_pct_max"], False),
    ("Metadata propagation (%)", metrics["metadata_propagation_pct"], THRESHOLDS["metadata_propagation_min"], True),
    ("Boundary violations (sample)", metrics["boundary_violations"], THRESHOLDS["boundary_violations_max"], False),
    ("Table integrity issues (%)", metrics["table_integrity_bad_pct"], THRESHOLDS["table_integrity_bad_pct_max"], False),
    ("Dense hard split (count)", metrics["dense_hard_split_count"], THRESHOLDS["dense_hard_split_count_max"], False),
    ("Dense oversized >3k (%)", metrics["dense_oversized_3k_pct"], THRESHOLDS["dense_oversized_3k_pct_max"], False),
    ("Dense tiny <50 chars (%)", metrics["dense_tiny_pct_lt50chars"], THRESHOLDS["dense_tiny_pct_max"], False),
    ("raw_table embed=False (%)", metrics["raw_table_embed_false_pct"], 100.0, True),
    ("table_summary raw link (%)", metrics["table_summary_has_raw_table_link_pct"], 100.0, True),
    ("procedure_record columns (%)", metrics["procedure_record_has_column_names_pct"], 95.0, True),
]

lines = [
    "=" * 60,
    "BÁO CÁO ĐÁNH GIÁ LEGAL CHUNKING DATASET",
    f"(memory-safe: viz sample ≤{VIZ_SAMPLE_ROWS:,}, boundary ≤{BOUNDARY_MAX_DOCS} docs)",
    "=" * 60,
    f"Chunks: {metrics['n_chunks']:,} | Docs: {metrics['n_docs']:,}",
    "",
]
for label, val, thr, hib in rows_report:
    lines.append(f"  {label:<36} {_fmt_metric(val):>10}  thr={thr:<8.4g}  {pass_fail(val, thr, hib)}")
lines.extend([
    "",
    f"Coverage status: {coverage_status}",
    f"Index mix: embed={metrics.get('embed_chunk_pct', 0):.1f}% | keyword={metrics.get('keyword_chunk_pct', 0):.1f}%",
    f"Dense coverage (mean, tham khảo): {_fmt_metric(metrics.get('dense_coverage_mean'))}",
    f"Corpus-only (tham khảo): hard_split={metrics['hard_split_count']} | oversized>3k={metrics['oversized_3k_pct']:.2f}%",
    f"Boundary: {len(boundary_df)} / {metrics.get('boundary_sample_docs', 0)} docs sampled (prose, embed=True)",
    "=" * 60,
])
print("\n".join(lines))


# =============================================================================
# CELL 8 — Chunk lớn (filter trước khi collect)
# =============================================================================


n_large = (
    metrics_lf.filter(pl.col("char_len") >= LARGE_CHUNK_THRESHOLD)
    .select(pl.len())
    .collect(engine="streaming")
    .item()
)
if n_large:
    large_full = (
        chunks_lf.with_columns(pl.col("chunk_text").str.len_chars().alias("char_len"))
        .filter(pl.col("char_len") >= LARGE_CHUNK_THRESHOLD)
        .select("doc_id", "chunk_id", "chunk_type", "char_len", "chunk_text")
        .collect(engine="streaming")
    )

    def _classify_row(ct: str, text: str) -> str:
        if ct in table_types or _has_table_body(text):
            return "table_or_appendix"
        low = (text or "").lower()[:500]
        if "phụ lục" in low or "phu luc" in low:
            return "appendix"
        return "long_prose"

    classes = [
        _classify_row(r["chunk_type"], r["chunk_text"])
        for r in large_full.iter_rows(named=True)
    ]
    large_full = large_full.with_columns(pl.Series("large_class", classes))
    print(f"\nLarge chunks (>={LARGE_CHUNK_THRESHOLD}): {large_full.height}")
    print(large_full.group_by("large_class").len())

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    lpd = large_full.to_pandas()
    sns.barplot(data=lpd, x="large_class", y="char_len", estimator=np.median, ax=axes[0])
    sns.countplot(data=lpd, x="chunk_type", hue="large_class", ax=axes[1])
    axes[1].tick_params(axis="x", rotation=30)
    show_fig()

    print("\n--- Preview chunk lớn (tối đa 15) ---")
    for row in large_full.head(15).iter_rows(named=True):
        print(f"\n[doc={row['doc_id']} | {row['chunk_id']} | len={row['char_len']}]")
        print((row["chunk_text"] or "")[:1200])
    del large_full, lpd
else:
    print(f"\nKhông có chunk >= {LARGE_CHUNK_THRESHOLD} ký tự.")
gc.collect()


# =============================================================================
# CELL 9 — Overview (aggregates + sample hist)
# =============================================================================

_hist_lf = metrics_lf.filter(pl.col("char_len") < 10_000).select("char_len")
_hist_n = _hist_lf.select(pl.len()).collect(engine="streaming").item()
if _hist_n > VIZ_SAMPLE_ROWS:
    hist_sample = _hist_lf.collect(engine="streaming").sample(n=VIZ_SAMPLE_ROWS, seed=RANDOM_SEED).to_pandas()
else:
    hist_sample = _hist_lf.collect(engine="streaming").to_pandas()

fig = plt.figure(figsize=(16, 10), layout="constrained")
gs = GridSpec(2, 3, figure=fig, hspace=0.35, wspace=0.3)
ax0 = fig.add_subplot(gs[0, 0])
sns.histplot(hist_sample, x="char_len", bins=50, kde=True, color=PALETTE_MAIN[0], ax=ax0)
ax0.set_xscale("log")
ax0.set_title("A. char_len (sample)")

ax1 = fig.add_subplot(gs[0, 1])
top8 = pd.Series(metrics["chunk_type_counts"]).nlargest(8)
sns.barplot(x=top8.values, y=top8.index, palette=[PALETTE_COOL(i / 8) for i in range(8)], ax=ax1)
ax1.set_title("B. Top chunk_type")

ax2 = fig.add_subplot(gs[0, 2])
fq = pd.Series(metrics.get("quality_flag_counts", {})).sort_values().tail(10)
if len(fq):
    sns.barplot(x=fq.values, y=fq.index, palette="magma", ax=ax2)
ax2.set_title("C. quality_flags")

ax3 = fig.add_subplot(gs[1, 0])
if len(coverage_df):
    sns.histplot(coverage_df["coverage"], bins=40, kde=True, ax=ax3)
ax3.set_title("D. Coverage")

ax4 = fig.add_subplot(gs[1, 1])
rates = pd.DataFrame({
    "metric": ["Dense tiny", "Dense over 3k", "Orphan", "Dense hard split"],
    "pct": [
        metrics["dense_tiny_pct_lt50chars"],
        metrics["dense_oversized_3k_pct"],
        metrics["orphan_pct"],
        100.0 * metrics["dense_hard_split_count"] / max(metrics["embed_chunk_count"], 1),
    ],
})
norm = mcolors.Normalize(vmin=0, vmax=max(rates["pct"].max(), 5))
ax4.barh(rates["metric"], rates["pct"], color=[PALETTE_WARM(norm(v)) for v in rates["pct"]])
ax4.set_title("E. Tỷ lệ cảnh báo")

ax5 = fig.add_subplot(gs[1, 2])
ax5.axis("off")
y = 0.95
for label, val, thr, hib in rows_report:
    st = pass_fail(val, thr, hib)
    ax5.text(0.02, y, f"{label}: {_fmt_metric(val)} ({st})", fontsize=8,
             color="#00b894" if st == "PASS" else "#d63031", transform=ax5.transAxes)
    y -= 0.12
fig.suptitle("Legal Chunking Evaluation — Overview", fontsize=14)
show_fig(use_tight=False)

print("\n=== HOÀN TẤT ĐÁNH GIÁ ===")
