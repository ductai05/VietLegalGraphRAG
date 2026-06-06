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
import hashlib
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
HAS_FLAGS_JSON = "quality_flags_json" in _schema
HAS_SECTION_LIST = "section_path" in _schema
HAS_EMBED_COL = "embed" in _schema
HAS_KEYWORD_COL = "keyword_index" in _schema
HAS_RAW_TABLE_ID = "raw_table_id" in _schema
HAS_TABLE_COLUMNS = "table_columns" in _schema
HAS_ANSWER_SOURCE = "answer_source" in _schema
HAS_NO_ANSWER_SUMMARY = "do_not_answer_from_summary" in _schema
HAS_TOKEN_COL = "token_estimate" in _schema
if not HAS_FLAGS_LIST and not HAS_FLAGS_JSON:
    raise ValueError("chunks.parquet thiếu cả `quality_flags` và `quality_flags_json`")

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

    token_expr = (
        pl.col("token_estimate").fill_null(0).cast(pl.Int64)
        if HAS_TOKEN_COL
        else (pl.col("chunk_text").str.len_chars() // 4).cast(pl.Int64)
    )
    lf = chunks_lf.select(
        *cols,
        pl.col("chunk_text").str.len_chars().alias("char_len"),
        pl.max_horizontal(token_expr, pl.lit(1)).alias("token_est"),
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


METRICS_CACHE_VERSION = "v5"
_chunks_stat = CHUNKS_PATH.stat()
_metadata_stat = METADATA_PATH.stat()
_cache_fingerprint = hashlib.sha1(
    (
        f"{CHUNKS_PATH.resolve()}:{_chunks_stat.st_size}:"
        f"{_chunks_stat.st_mtime_ns}:{METADATA_PATH.resolve()}:"
        f"{_metadata_stat.st_size}:{_metadata_stat.st_mtime_ns}:"
        f"{METRICS_CACHE_VERSION}"
    ).encode("utf-8")
).hexdigest()[:12]
METRICS_CACHE = WORK_DIR / f"metrics_narrow_{_cache_fingerprint}.parquet"
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
        (
            pl.col("is_tiny_metric").filter(pl.col("is_embeddable")).mean() * 100
        ).alias("dense_tiny_pct_lt50chars"),
        (
            pl.col("is_oversized_3k")
            .filter(
                pl.col("is_embeddable")
                & (~pl.col("chunk_type").is_in(list(OVERSIZE_EXEMPT_TYPES)))
            )
            .mean()
            * 100
        ).alias("dense_oversized_3k_pct"),
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
        100.0 * summary_link_stats["valid"] / summary_link_stats["n"]
        if summary_link_stats["n"] else None
    )
else:
    metrics["table_summary_has_raw_table_link_pct"] = None

if HAS_EMBED_COL:
    flag_stats = chunks_lf.select(
        (
            (~pl.col("embed").fill_null(True))
            .filter(pl.col("chunk_type") == "raw_table")
            .mean() * 100
        ).alias("raw_table_embed_false_pct"),
        (
            pl.col("embed").fill_null(False)
            .filter(pl.col("chunk_type") == "table_summary")
            .mean() * 100
        ).alias("table_summary_embed_true_pct"),
    ).collect(engine="streaming").row(0, named=True)
    metrics.update(flag_stats)
else:
    metrics["raw_table_embed_false_pct"] = None
    metrics["table_summary_embed_true_pct"] = None

if HAS_TABLE_COLUMNS:
    proc_column_stats = chunks_lf.filter(
        pl.col("chunk_type") == "procedure_record"
    ).select(
        pl.len().alias("n"),
        (pl.col("table_columns").list.len() > 0).sum().alias("valid"),
    ).collect(engine="streaming").row(0, named=True)
    metrics["procedure_record_has_column_names_pct"] = (
        100.0 * proc_column_stats["valid"] / proc_column_stats["n"]
        if proc_column_stats["n"] else None
    )
else:
    metrics["procedure_record_has_column_names_pct"] = None
if HAS_ANSWER_SOURCE and HAS_NO_ANSWER_SUMMARY:
    answer_rule = table_summary_lf.select(
        pl.len().alias("n"),
        (
            (pl.col("answer_source") == "raw_table")
            & pl.col("do_not_answer_from_summary")
        ).sum().alias("valid"),
    ).collect(engine="streaming").row(0, named=True)
    metrics["table_summary_answer_rule_pct"] = (
        100.0 * answer_rule["valid"] / answer_rule["n"]
        if answer_rule["n"] else None
    )
else:
    metrics["table_summary_answer_rule_pct"] = None
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


def _fmt_metric(val: Optional[float]) -> str:
    return "N/A" if val is None else f"{val:.4g}"


def pass_fail(val: Optional[float], thr: float, higher: bool) -> str:
    if val is None:
        return "N/A"
    return "PASS" if (val >= thr if higher else val <= thr) else "FAIL"


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


def _kpi_card(ax, title: str, value: str, subtitle: str, color: str) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0.04, 0.08), 0.92, 0.84, fc=color, alpha=0.12, ec=color, lw=1.5))
    ax.text(0.5, 0.72, title, ha="center", va="center", fontsize=10, color="#636e72")
    ax.text(0.5, 0.46, value, ha="center", va="center", fontsize=18, fontweight="bold", color=color)
    ax.text(0.5, 0.18, subtitle, ha="center", va="center", fontsize=8.5, color="#636e72")


def render_coverage_dashboard(
    cov_df: pd.DataFrame,
    status: str,
    summary: Dict[str, Any],
) -> None:
    fig = plt.figure(figsize=(14, 8), layout="constrained")
    gs = GridSpec(3, 4, figure=fig, height_ratios=[0.55, 0.85, 2.4], hspace=0.4, wspace=0.3)

    cov_ok = (
        summary.get("coverage_mean") is not None
        and summary["coverage_mean"] >= THRESHOLDS["coverage_target"]
    )
    status_color = "#00b894" if cov_ok else ("#fdcb6e" if len(cov_df) else "#b2bec3")
    ax_status = fig.add_subplot(gs[0, :])
    ax_status.axis("off")
    ax_status.add_patch(plt.Rectangle((0, 0.15), 1, 0.7, fc=status_color, alpha=0.15, ec=status_color, lw=2))
    ax_status.text(
        0.02, 0.5, f"Coverage: {status}",
        ha="left", va="center", fontsize=12, fontweight="bold", color="#2d3436",
    )
    if len(cov_df):
        ax_status.text(
            0.98, 0.5,
            f"{'PASS' if cov_ok else 'CHECK'}  (target ≥ {THRESHOLDS['coverage_target']:.3f})",
            ha="right", va="center", fontsize=12, fontweight="bold", color=status_color,
        )

    kpi_specs = [
        ("Chunks", f"{summary['n_chunks']:,}", f"{summary['n_docs']:,} documents", "#0984e3"),
        ("Orphan", f"{summary['orphan_pct']:.2f}%", f"{summary['orphan_count']:,} chunks", "#6c5ce7"),
        ("Embed mix", f"{summary.get('embed_chunk_pct', 0):.1f}%", f"{summary.get('embed_chunk_count', 0):,} chunks", "#00cec9"),
        ("Metadata", f"{summary['metadata_propagation_pct']:.1f}%", "docs có metadata", "#e17055"),
    ]
    for i, spec in enumerate(kpi_specs):
        _kpi_card(fig.add_subplot(gs[1, i]), *spec)

    ax_hist = fig.add_subplot(gs[2, :])
    if len(cov_df):
        plot_cov = cov_df.sample(min(len(cov_df), 80_000), random_state=RANDOM_SEED)
        sns.histplot(
            data=plot_cov, x="coverage", bins=50, kde=True,
            color="#0984e3", edgecolor="white", linewidth=0.4,
            ax=ax_hist, stat="density",
        )
        sns.kdeplot(
            data=plot_cov, x="dense_coverage", color="#e84393", lw=2.2,
            label="Dense coverage KDE", ax=ax_hist,
        )
        ax_hist.axvline(THRESHOLDS["coverage_target"], color="#00b894", ls="--", lw=2, label="Target")
        ax_hist.axvline(THRESHOLDS["coverage_min"], color="#d63031", ls="--", lw=1.5, label="Min 95%")
        mean_cov = summary.get("coverage_mean")
        if mean_cov is not None:
            ax_hist.axvline(mean_cov, color="#2d3436", ls="-", lw=1.5, alpha=0.7, label=f"Mean={mean_cov:.3f}")
        ax_hist.set_xlim(0, min(1.25, plot_cov["coverage"].quantile(0.995) + 0.05))
        ax_hist.set_title(
            f"Phân phối coverage theo document  |  "
            f"mean={_fmt_metric(summary.get('coverage_mean'))}  "
            f"median={_fmt_metric(summary.get('coverage_median'))}  "
            f"dense_mean={_fmt_metric(summary.get('dense_coverage_mean'))}  "
            f"docs<95%={summary.get('coverage_docs_below_95pct', 'N/A')}",
            loc="left", fontsize=11,
        )
        ax_hist.legend(loc="upper left", fontsize=8, ncol=2)
    else:
        ax_hist.axis("off")
        ax_hist.text(0.5, 0.5, status, ha="center", va="center", fontsize=12, color="#636e72")
    fig.suptitle("Coverage & Corpus Overview", fontsize=14, fontweight="bold", y=1.02)
    show_fig(use_tight=False)


render_coverage_dashboard(coverage_df, coverage_status, metrics)
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
    lf = metrics_lf.filter(pl.col("token_est") < 4000).select("token_est", "chunk_type")
    n = lf.select(pl.len()).collect(engine="streaming").item()
    if n > max_rows:
        return lf.collect(engine="streaming").sample(n=max_rows, seed=RANDOM_SEED).to_pandas()
    return lf.collect(engine="streaming").to_pandas()


viz_pd = load_viz_sample()
gc.collect()

token_bins = [0, 50, 100, 200, 400, 800, 1200, 2000, 3000, 5000]
viz_pd["token_bin"] = pd.cut(
    viz_pd["token_est"], bins=token_bins, right=False, include_lowest=True,
)
bin_counts = (
    viz_pd.groupby("token_bin", observed=True)
    .size()
    .reset_index(name="n_chunks")
)
bin_counts["token_mid"] = bin_counts["token_bin"].apply(lambda b: (b.left + b.right) / 2)
norm = mcolors.Normalize(vmin=bin_counts["token_mid"].min(), vmax=bin_counts["token_mid"].max())
bar_colors = [PALETTE_GRAD(norm(v)) for v in bin_counts["token_mid"]]

fig, axes = plt.subplots(1, 2, figsize=(14, 5.5), layout="constrained")
axes[0].bar(
    range(len(bin_counts)), bin_counts["n_chunks"], color=bar_colors,
    edgecolor="white", linewidth=0.6,
)
axes[0].set_xticks(range(len(bin_counts)))
axes[0].set_xticklabels(
    [f"{int(b.left)}–{int(b.right)}" for b in bin_counts["token_bin"]],
    rotation=35, ha="right", fontsize=8,
)
axes[0].set_ylabel("Số chunks")
axes[0].set_xlabel("Token estimate / chunk")
axes[0].set_title(f"Phân phối số lượng chunks theo token (sample ≤{len(viz_pd):,})")
sm = plt.cm.ScalarMappable(cmap=PALETTE_GRAD, norm=norm)
sm.set_array([])
cbar = fig.colorbar(sm, ax=axes[0], fraction=0.03, pad=0.02)
cbar.set_label("Token (gradient)")

sns.histplot(
    data=viz_pd, x="token_est", bins=60, kde=True,
    color="#6c5ce7", edgecolor="white", linewidth=0.3,
    ax=axes[1], stat="count",
)
axes[1].set_xlabel("Token estimate / chunk")
axes[1].set_ylabel("Số chunks")
axes[1].set_title("Histogram token estimate (toàn sample)")
show_fig(use_tight=False)
del viz_pd, bin_counts
gc.collect()

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
    ax.set_title(
        "chunk_type x emitted quality_flags (embed=True only; tiny flag <300 chars)"
    )
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
if HAS_RAW_TABLE_ID:
    table_select.append("raw_table_id")
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
        raw_parent_id = row.get("raw_table_id") if HAS_RAW_TABLE_ID else None
        valid = (
            _has_table_header(text)
            or raw_header_by_id.get(raw_parent_id, False)
            or raw_header_by_id.get(row["parent_id"], False)
        )
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
def _pct_or_none(valid: int, total: int) -> Optional[float]:
    return 100.0 * valid / total if total else None


def _pct_text(value: Optional[float]) -> str:
    return "N/A" if value is None else f"{value:.2f}"


metrics["raw_table_has_header_pct"] = _pct_or_none(counts["raw_table_valid"], counts["raw_table_total"])
metrics["table_part_has_header_or_parent_header_pct"] = _pct_or_none(counts["table_part_valid"], counts["table_part_total"])
metrics["procedure_record_has_column_context_pct"] = _pct_or_none(counts["procedure_record_valid"], counts["procedure_record_total"])
metrics["table_integrity_bad_pct"] = _pct_or_none(len(table_issues_df), integrity_total)
metrics["table_integrity_issues"] = len(table_issues_df)
del table_rows
gc.collect()


def render_table_integrity_dashboard(
    counts: Dict[str, int],
    issues_df: pd.DataFrame,
    summary: Dict[str, Any],
    integrity_n: int,
) -> None:
    integrity_rows = [
        {
            "check": "raw_table header",
            "valid_pct": summary.get("raw_table_has_header_pct"),
            "valid": counts["raw_table_valid"],
            "total": counts["raw_table_total"],
            "thr": 95.0,
        },
        {
            "check": "table_part header/parent",
            "valid_pct": summary.get("table_part_has_header_or_parent_header_pct"),
            "valid": counts["table_part_valid"],
            "total": counts["table_part_total"],
            "thr": 95.0,
        },
        {
            "check": "procedure_record context",
            "valid_pct": summary.get("procedure_record_has_column_context_pct"),
            "valid": counts["procedure_record_valid"],
            "total": counts["procedure_record_total"],
            "thr": 95.0,
        },
    ]
    integrity_df = pd.DataFrame(integrity_rows)
    integrity_df["invalid"] = integrity_df["total"] - integrity_df["valid"]
    integrity_df["invalid_pct"] = np.where(
        integrity_df["total"] > 0,
        100.0 * integrity_df["invalid"] / integrity_df["total"],
        0.0,
    )

    link_rows = [
        ("summary→raw link", summary.get("table_summary_has_raw_table_link_pct"), 100.0),
        ("raw embed=False", summary.get("raw_table_embed_false_pct"), 100.0),
        ("summary embed=True", summary.get("table_summary_embed_true_pct"), 100.0),
        ("procedure columns", summary.get("procedure_record_has_column_names_pct"), 95.0),
        ("answer rule", summary.get("table_summary_answer_rule_pct"), 100.0),
    ]
    link_df = pd.DataFrame(link_rows, columns=["metric", "value", "thr"])
    link_df = link_df.dropna(subset=["value"])

    bad_pct = summary.get("table_integrity_bad_pct")
    thr_bad = THRESHOLDS["table_integrity_bad_pct_max"]
    overall_ok = bad_pct is not None and bad_pct <= thr_bad
    banner_color = "#00b894" if overall_ok else "#d63031"

    fig = plt.figure(figsize=(14, 9), layout="constrained")
    gs = GridSpec(2, 2, figure=fig, height_ratios=[1.1, 1.0], width_ratios=[1.15, 0.85])

    ax0 = fig.add_subplot(gs[0, 0])
    y_pos = np.arange(len(integrity_df))
    ax0.barh(y_pos, integrity_df["valid_pct"].fillna(0), color="#00b894", height=0.55, label="Valid %")
    ax0.barh(
        y_pos, integrity_df["invalid_pct"], left=integrity_df["valid_pct"].fillna(0),
        color="#d63031", height=0.55, label="Invalid %",
    )
    for i, row in integrity_df.iterrows():
        if row["total"]:
            ax0.text(
                102, i, f"{int(row['valid']):,}/{int(row['total']):,}",
                va="center", fontsize=9, color="#636e72",
            )
    ax0.set_yticks(y_pos)
    ax0.set_yticklabels(integrity_df["check"])
    ax0.set_xlim(0, 108)
    ax0.set_xlabel("Tỷ lệ (%)")
    ax0.set_title("Integrity theo loại chunk bảng (parser checks)", loc="left")
    ax0.legend(loc="lower right", fontsize=8)
    ax0.axvline(95, color="#2d3436", ls="--", lw=1, alpha=0.5)

    ax1 = fig.add_subplot(gs[0, 1])
    if len(issues_df):
        issue_counts = (
            issues_df.groupby(["issue", "chunk_type"])
            .size()
            .reset_index(name="count")
        )
        sns.barplot(
            data=issue_counts, y="issue", x="count", hue="chunk_type",
            palette=sns.color_palette("Set2", n_colors=issue_counts["chunk_type"].nunique()),
            ax=ax1, edgecolor="white",
        )
        ax1.set_title(f"Phân loại lỗi ({len(issues_df):,} issues)", loc="left")
        ax1.set_xlabel("Số chunks lỗi")
        ax1.legend(title="chunk_type", fontsize=7, title_fontsize=8, loc="lower right")
    else:
        ax1.axis("off")
        ax1.text(0.5, 0.55, "Không có lỗi parser", ha="center", va="center", fontsize=13, color="#00b894")
        ax1.text(0.5, 0.35, "Tất cả raw_table / table_part / procedure_record đạt", ha="center", va="center", fontsize=9, color="#636e72")

    ax2 = fig.add_subplot(gs[1, 0])
    table_vol = (
        pd.Series({k: summary["chunk_type_counts"].get(k, 0) for k in table_types})
        .sort_values(ascending=True)
    )
    vol_colors = sns.color_palette("crest", n_colors=len(table_vol))
    ax2.barh(table_vol.index, table_vol.values, color=vol_colors, edgecolor="white")
    for i, (ct, n) in enumerate(table_vol.items()):
        ax2.text(n + table_vol.max() * 0.01, i, f"{n:,}", va="center", fontsize=8)
    ax2.set_xlabel("Số chunks")
    ax2.set_title("Khối lượng chunk theo loại bảng", loc="left")

    ax3 = fig.add_subplot(gs[1, 1])
    if len(link_df):
        link_df = link_df.copy()
        link_df["status"] = link_df.apply(
            lambda r: "PASS" if r["value"] >= r["thr"] else "CHECK", axis=1,
        )
        status_palette = {"PASS": "#00b894", "CHECK": "#e17055", "FAIL": "#d63031"}
        sns.barplot(
            data=link_df, y="metric", x="value",
            hue="status", dodge=False, palette=status_palette, ax=ax3, edgecolor="white",
        )
        for _, row in link_df.iterrows():
            ax3.axvline(row["thr"], color="#636e72", ls=":", lw=1, alpha=0.6)
        ax3.set_xlim(0, 105)
        ax3.set_xlabel("Tỷ lệ (%)")
        ax3.set_title("Liên kết & index policy (table pipeline)", loc="left")
        ax3.legend(title="", fontsize=8, loc="lower right")
    else:
        ax3.axis("off")
        ax3.text(0.5, 0.5, "Không có cột link/embed trong schema", ha="center", va="center", fontsize=10, color="#636e72")

    fig.suptitle(
        f"Table Integration  |  issues={_pct_text(bad_pct)}% ({summary.get('table_integrity_issues', 0):,} / {integrity_n:,})  "
        f"[{'PASS' if overall_ok else 'CHECK'} ≤ {thr_bad}%]",
        fontsize=13, fontweight="bold", color=banner_color, y=1.02,
    )
    show_fig(use_tight=False)


render_table_integrity_dashboard(counts, table_issues_df, metrics, integrity_total)


# =============================================================================
# CELL 7 — Báo cáo (visual)
# =============================================================================


def render_evaluation_report(
    summary: Dict[str, Any],
    cov_status: str,
    boundary_sample: pd.DataFrame,
) -> None:
    rows_report = [
        ("Coverage (mean)", summary["coverage_mean"], THRESHOLDS["coverage_target"], True, "corpus"),
        ("Orphan (%)", summary["orphan_pct"], THRESHOLDS["orphan_pct_max"], False, "corpus"),
        ("Metadata propagation (%)", summary["metadata_propagation_pct"], THRESHOLDS["metadata_propagation_min"], True, "corpus"),
        ("Boundary violations (sample)", summary["boundary_violations"], THRESHOLDS["boundary_violations_max"], False, "corpus"),
        ("Table integrity issues (%)", summary["table_integrity_bad_pct"], THRESHOLDS["table_integrity_bad_pct_max"], False, "corpus"),
        ("Dense hard split (count)", summary["dense_hard_split_count"], THRESHOLDS["dense_hard_split_count_max"], False, "dense"),
        ("Dense oversized >3k (%)", summary["dense_oversized_3k_pct"], THRESHOLDS["dense_oversized_3k_pct_max"], False, "dense"),
        ("Dense tiny <50 chars (%)", summary["dense_tiny_pct_lt50chars"], THRESHOLDS["dense_tiny_pct_max"], False, "dense"),
        ("raw_table embed=False (%)", summary["raw_table_embed_false_pct"], 100.0, True, "table"),
        ("table_summary raw link (%)", summary["table_summary_has_raw_table_link_pct"], 100.0, True, "table"),
        ("procedure_record columns (%)", summary["procedure_record_has_column_names_pct"], 95.0, True, "table"),
    ]
    report_df = pd.DataFrame(
        rows_report, columns=["metric", "value", "threshold", "higher_is_better", "group"],
    )
    report_df["status"] = report_df.apply(
        lambda r: pass_fail(r["value"], r["threshold"], r["higher_is_better"]), axis=1,
    )
    status_colors = {"PASS": "#00b894", "FAIL": "#d63031", "N/A": "#b2bec3"}
    report_df["color"] = report_df["status"].map(status_colors)

    fig = plt.figure(figsize=(14, 9), layout="constrained")
    gs = GridSpec(2, 2, figure=fig, height_ratios=[0.35, 1.65], width_ratios=[1.2, 0.8])

    ax_head = fig.add_subplot(gs[0, :])
    ax_head.axis("off")
    n_pass = (report_df["status"] == "PASS").sum()
    n_fail = (report_df["status"] == "FAIL").sum()
    n_na = (report_df["status"] == "N/A").sum()
    head_color = "#00b894" if n_fail == 0 else "#e17055"
    ax_head.add_patch(plt.Rectangle((0, 0.1), 1, 0.8, fc=head_color, alpha=0.12, ec=head_color, lw=2))
    ax_head.text(
        0.02, 0.5,
        f"BÁO CÁO ĐÁNH GIÁ  |  {summary['n_chunks']:,} chunks · {summary['n_docs']:,} docs",
        ha="left", va="center", fontsize=13, fontweight="bold",
    )
    ax_head.text(
        0.98, 0.5,
        f"PASS {n_pass}  ·  FAIL {n_fail}  ·  N/A {n_na}",
        ha="right", va="center", fontsize=11, fontweight="bold", color=head_color,
    )

    ax_tbl = fig.add_subplot(gs[1, 0])
    ax_tbl.axis("off")
    table_rows = []
    for _, row in report_df.iterrows():
        table_rows.append([
            row["metric"],
            _fmt_metric(row["value"]),
            f"{row['threshold']:.4g}",
            row["status"],
        ])
    tbl = ax_tbl.table(
        cellText=table_rows,
        colLabels=["Metric", "Value", "Threshold", "Status"],
        loc="center", cellLoc="left", colLoc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.45)
    for (r, c), cell in tbl.get_celld().items():
        if r == 0:
            cell.set_facecolor("#2d3436")
            cell.set_text_props(color="white", fontweight="bold")
            continue
        if c == 3:
            cell.set_facecolor(status_colors.get(table_rows[r - 1][3], "#dfe6e9"))
            cell.set_text_props(color="white", fontweight="bold")
        elif r % 2 == 0:
            cell.set_facecolor("#f8f9fa")

    ax_gauge = fig.add_subplot(gs[1, 1])
    gauge_df = report_df[report_df["status"] != "N/A"].copy()
    gauge_df["ratio"] = gauge_df.apply(
        lambda r: (
            min(1.5, r["value"] / r["threshold"]) if r["higher_is_better"] and r["threshold"]
            else min(1.5, r["value"] / max(r["threshold"], 1e-9))
        ),
        axis=1,
    )
    y = np.arange(len(gauge_df))
    bar_colors = [
        status_colors[s] if s == "FAIL" else PALETTE_COOL(0.2 + 0.6 * min(row["ratio"], 1.0))
        for row, s in zip(gauge_df.to_dict("records"), gauge_df["status"])
    ]
    ax_gauge.barh(y, gauge_df["value"], color=bar_colors, height=0.6, edgecolor="white")
    for i, (_, row) in enumerate(gauge_df.iterrows()):
        ax_gauge.plot([row["threshold"], row["threshold"]], [i - 0.32, i + 0.32], color="#2d3436", lw=2)
        ax_gauge.text(
            row["value"] + max(gauge_df["value"].max() * 0.02, 0.01), i,
            row["status"], va="center", fontsize=8, fontweight="bold", color=row["color"],
        )
    ax_gauge.set_yticks(y)
    ax_gauge.set_yticklabels([m[:28] + "…" if len(m) > 28 else m for m in gauge_df["metric"]], fontsize=8)
    ax_gauge.set_title("Value vs threshold (| = ngưỡng)", loc="left", fontsize=10)
    ax_gauge.invert_yaxis()

    foot = (
        f"{cov_status}\n"
        f"Index: embed {summary.get('embed_chunk_pct', 0):.1f}% · keyword {summary.get('keyword_chunk_pct', 0):.1f}%  |  "
        f"Dense cov mean {_fmt_metric(summary.get('dense_coverage_mean'))}  |  "
        f"Boundary {len(boundary_sample)} / {summary.get('boundary_sample_docs', 0)} docs"
    )
    fig.text(0.02, 0.01, foot, fontsize=8, color="#636e72", va="bottom")
    fig.suptitle(
        f"Legal Chunking QA  (viz ≤{VIZ_SAMPLE_ROWS:,}, boundary ≤{BOUNDARY_MAX_DOCS} docs)",
        fontsize=12, y=1.01,
    )
    show_fig(use_tight=False)


render_evaluation_report(metrics, coverage_status, boundary_df)


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
    lpd = large_full.to_pandas()
    class_order = (
        lpd.groupby("large_class")["char_len"].median().sort_values(ascending=False).index.tolist()
    )
    n_classes = len(class_order)
    class_palette = sns.color_palette("turbo", n_colors=n_classes)

    fig = plt.figure(figsize=(15, 6.5), layout="constrained")
    gs = GridSpec(1, 3, figure=fig, width_ratios=[1.1, 1.2, 0.9])

    ax0 = fig.add_subplot(gs[0, 0])
    sns.boxenplot(
        data=lpd, x="large_class", y="char_len", order=class_order,
        palette=class_palette, ax=ax0, linewidth=0.8,
    )
    ax0.set_yscale("log")
    ax0.set_title(f"Phân phối kích thước (n={lpd.shape[0]:,})", loc="left")
    ax0.set_xlabel("")
    ax0.tick_params(axis="x", rotation=20)

    ax1 = fig.add_subplot(gs[0, 1])
    top_types_large = lpd["chunk_type"].value_counts().head(8).index.tolist()
    lpd_top = lpd[lpd["chunk_type"].isin(top_types_large)].copy()
    sns.stripplot(
        data=lpd_top, x="chunk_type", y="char_len", hue="large_class",
        order=top_types_large, hue_order=class_order, palette=class_palette,
        size=3.5, alpha=0.65, jitter=0.25, ax=ax1,
    )
    ax1.set_yscale("log")
    ax1.set_title("Chunk lớn theo chunk_type (top 8)", loc="left")
    ax1.tick_params(axis="x", rotation=30)
    ax1.legend(title="class", fontsize=7, title_fontsize=8, loc="upper right")

    ax2 = fig.add_subplot(gs[0, 2])
    class_counts = lpd["large_class"].value_counts().reindex(class_order)
    norm_cls = mcolors.Normalize(vmin=0, vmax=max(n_classes - 1, 1))
    wedge_colors = [plt.cm.turbo(norm_cls(i)) for i in range(n_classes)]
    wedges, texts, autotexts = ax2.pie(
        class_counts.values, labels=class_counts.index, autopct="%1.1f%%",
        colors=wedge_colors, startangle=140,
        wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.2),
        pctdistance=0.75,
    )
    for t in autotexts:
        t.set_fontsize(8)
        t.set_fontweight("bold")
    ax2.set_title(f"Tỷ lệ phân loại\n(≥{LARGE_CHUNK_THRESHOLD:,} chars)", loc="center")

    fig.suptitle(
        f"Large Chunks Overview  |  median chars by class: "
        + ", ".join(f"{c}={lpd.loc[lpd['large_class']==c,'char_len'].median():,.0f}" for c in class_order),
        fontsize=11, y=1.02,
    )
    show_fig(use_tight=False)
    del large_full, lpd
else:
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.axis("off")
    ax.text(
        0.5, 0.5, f"Không có chunk ≥ {LARGE_CHUNK_THRESHOLD:,} ký tự",
        ha="center", va="center", fontsize=13, color="#00b894",
    )
    show_fig()
gc.collect()
