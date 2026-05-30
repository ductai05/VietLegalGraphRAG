# %% [markdown]
# # EDA + Merge Validation for Vietnamese Legal Documents
#
# Script notebook copy được vào Kaggle.
# Mục tiêu:
# - EDA 4 file trong folder `merged`.
# - Chứng minh dữ liệu merged được tạo từ `legacy` + `data` bằng mapping one-to-one chính xác.
# - Kiểm chứng `content` và `relationships` đã remap từ data ID sang legacy ID qua crosswalk.

# %% [code]
import os
import re
import warnings
from pathlib import Path

import polars as pl
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from IPython.display import display, Markdown

pl.Config.set_tbl_cols(-1)
pl.Config.set_tbl_rows(30)
pl.Config.set_fmt_str_lengths(180)
pl.Config.set_tbl_width_chars(240)


def md(text: str):
    display(Markdown(text))


warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
LEGAL_BREAK_RE = re.compile(r"(?=\b(?:Căn cứ|Xét|Theo đề nghị|QUYẾT ĐỊNH|Điều\s+\d+|Chương\s+[IVXLCDM\d]+|Mục\s+\d+|Phần\s+[IVXLCDM\d]+)\b)")


def _looks_like_html(text):
    return bool(HTML_TAG_RE.search(text[:5000]))


def _strip_html_fast(text):
    try:
        soup = BeautifulSoup(text, "lxml")
    except Exception:
        soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["title", "script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _legal_raw_lines(text):
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"(Điều\s+\d+)\s*\n*\s*:", r"\1:", text)
    text = re.sub(r"\s+(?=(?:Điều\s+\d+|Chương\s+[IVXLCDM\d]+|Mục\s+\d+|Phần\s+[IVXLCDM\d]+)\b)", "\n", text)
    lines = []
    for chunk in text.split("\n"):
        chunk = re.sub(r"[ \t\f\v]+", " ", chunk).strip()
        if not chunk:
            continue
        parts = [part.strip() for part in LEGAL_BREAK_RE.split(chunk) if part.strip()]
        lines.extend(parts or [chunk])
    return lines


def _format_legal_lines(raw_lines):
    if not raw_lines:
        return ""

    merged_lines = []
    buffer = raw_lines[0]

    for curr in raw_lines[1:]:
        is_curr_header = curr.isupper() and len(curr) > 3
        is_curr_article = re.match(r"^Điều\s+\d+:", curr)
        is_curr_structural = re.match(r"^(?:Chương|Mục|Phần)\s+[IVXLCDM\d]+", curr)
        is_buffer_header = buffer.isupper() and len(buffer) > 3
        is_buffer_article = re.match(r"^Điều\s+\d+:", buffer)
        is_buffer_structural = re.match(r"^(?:Chương|Mục|Phần)\s+[IVXLCDM\d]+", buffer)
        is_split_word = len(buffer) <= 2
        is_unfinished_sentence = re.search(r"[a-zà-ỹ,;]\s*$", buffer)
        is_next_lowercase = curr[0].islower() if curr else False

        if (is_split_word or is_unfinished_sentence or is_next_lowercase) and not is_curr_header and not is_curr_article and not is_curr_structural and not is_buffer_header and not is_buffer_article and not is_buffer_structural:
            buffer += " " + curr
        else:
            merged_lines.append(buffer)
            buffer = curr

    merged_lines.append(buffer)

    final_output = []
    for line in merged_lines:
        line = re.sub(r"\s+", " ", line).strip()
        is_header = line.isupper() and len(line) > 3
        is_article = re.match(r"^Điều\s+\d+:", line)
        is_structural = re.match(r"^(?:Chương|Mục|Phần)\s+[IVXLCDM\d]+", line)

        if is_header or is_article or is_structural:
            if final_output and final_output[-1] != "":
                final_output.append("")
            final_output.append(line)
            if is_article:
                final_output.append("")
        else:
            final_output.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(final_output)).strip()


def preprocess_legal_text(content):
    if content is None:
        return ""
    text = str(content).strip()
    if not text:
        return ""
    if _looks_like_html(text):
        text = _strip_html_fast(text)
    return _format_legal_lines(_legal_raw_lines(text))


def find_dataset_root() -> Path:
    candidates = [
        Path("/kaggle/input/vietnamese-legal-documents"),
        Path("/kaggle/input/datasets/brdh7940/vietnamese-legal-documents"),
        Path("/kaggle/input"),
        Path("."),
    ]
    required = [
        "legacy/metadata.parquet",
        "legacy/content.parquet",
        "data/metadata.parquet",
        "data/content.parquet",
        "data/relationships.parquet",
        "merged/merged_metadata.parquet",
        "merged/merged_content.parquet",
        "merged/merged_relationships.parquet",
        "merged/data_to_legacy_crosswalk.parquet",
    ]
    for base in candidates:
        if not base.exists():
            continue
        search_roots = [base, *base.glob("**/vietnamese-legal-documents")]
        for root in search_roots:
            if all((root / rel).exists() for rel in required):
                return root
    raise FileNotFoundError("Không tìm thấy dataset root có đủ legacy/, data/, merged/ parquet files.")


ROOT = find_dataset_root()
LEGACY_DIR = ROOT / "legacy"
DATA_DIR = ROOT / "data"
MERGED_DIR = ROOT / "merged"

FILES = {
    "legacy_metadata": LEGACY_DIR / "metadata.parquet",
    "legacy_content": LEGACY_DIR / "content.parquet",
    "data_metadata": DATA_DIR / "metadata.parquet",
    "data_content": DATA_DIR / "content.parquet",
    "data_relationships": DATA_DIR / "relationships.parquet",
    "merged_metadata": MERGED_DIR / "merged_metadata.parquet",
    "merged_content": MERGED_DIR / "merged_content.parquet",
    "merged_relationships": MERGED_DIR / "merged_relationships.parquet",
    "crosswalk": MERGED_DIR / "data_to_legacy_crosswalk.parquet",
}

md(f"## Dataset root\n`{ROOT}`")
display(pl.DataFrame({"name": list(FILES), "path": [str(p) for p in FILES.values()]}))

# %% [markdown]
# ## 1. File inventory and schemas

# %% [code]
def scan(name: str) -> pl.LazyFrame:
    return pl.scan_parquet(str(FILES[name]))


def row_count(name: str) -> int:
    return scan(name).select(pl.len()).collect().item()


def schema_df(name: str) -> pl.DataFrame:
    schema = scan(name).collect_schema()
    return pl.DataFrame({
        "file": [name] * len(schema),
        "column": list(schema.names()),
        "dtype": [str(dtype) for dtype in schema.dtypes()],
    })

inventory = pl.DataFrame({
    "file": list(FILES),
    "rows": [row_count(name) for name in FILES],
    "columns": [len(scan(name).collect_schema()) for name in FILES],
})
display(inventory)
display(pl.concat([schema_df(name) for name in FILES], how="vertical"))

# %% [markdown]
# ## 2. Column-level EDA for merged files

# %% [code]
def column_stats(name: str) -> pl.DataFrame:
    lf = scan(name)
    schema = lf.collect_schema()
    total = row_count(name)
    rows = []
    for col, dtype in schema.items():
        base = lf.select(
            pl.col(col).null_count().alias("nulls"),
            pl.col(col).n_unique().alias("n_unique"),
        ).collect()
        null_count = base["nulls"][0]
        n_unique = base["n_unique"][0]
        detail = ""
        if null_count == total:
            detail = "ALL NULL"
        elif dtype == pl.String:
            len_stats = lf.select(
                pl.col(col).str.len_chars().mean().alias("len_avg"),
                pl.col(col).str.len_chars().max().alias("len_max"),
            ).collect()
            detail = f"len_avg={len_stats['len_avg'][0]:.1f}, len_max={len_stats['len_max'][0]}"
            if col not in {"content", "content_html", "legacy_content", "data_content"}:
                top = lf.group_by(col).agg(pl.len().alias("count")).sort("count", descending=True).head(1).collect().to_dicts()
                if top:
                    detail += f" | top={str(top[0][col])[:60]} ({top[0]['count']:,}x)"
        elif dtype.is_numeric():
            num_stats = lf.select(pl.col(col).min().alias("min"), pl.col(col).max().alias("max")).collect()
            detail = f"min={num_stats['min'][0]}, max={num_stats['max'][0]}"
        rows.append({
            "file": name,
            "column": col,
            "dtype": str(dtype),
            "n_unique": n_unique,
            "nulls": null_count,
            "null_pct": round(null_count / total * 100, 2) if total else 0,
            "detail": detail,
        })
    return pl.DataFrame(rows)

for name in ["merged_metadata", "merged_content", "merged_relationships", "crosswalk"]:
    md(f"### {name}")
    display(column_stats(name))

# %% [markdown]
# ## 3. Rebuild mapping from source files
#
# Merge logic cần chứng minh:
# - `legacy` là gốc, nên số dòng `merged_metadata` và `merged_content` phải bằng legacy.
# - `data` được map vào `legacy` bằng key chuẩn hóa: `document_number + issuance_date`.
# - Chỉ chấp nhận key one-to-one: key xuất hiện đúng 1 lần ở legacy và đúng 1 lần ở data.
# - `crosswalk` lưu `legacy_id -> data_id` cho các match hợp lệ.

# %% [code]
COL_MAP = {
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
JOIN_COLS = ["document_number", "issuance_date"]


def clean_expr(col: str) -> pl.Expr:
    x = pl.col(col).cast(pl.Utf8, strict=False).str.replace_all(r"\s+", " ").str.strip_chars()
    return pl.when(x == "").then(None).otherwise(x)


def date_expr(col: str) -> pl.Expr:
    x = clean_expr(col)
    return pl.coalesce(
        x.str.strptime(pl.Date, "%d/%m/%Y", strict=False),
        x.str.strptime(pl.Date, "%Y-%m-%d", strict=False),
    ).dt.strftime("%Y-%m-%d")


def add_key(lf: pl.LazyFrame, cols: list[str]) -> pl.LazyFrame:
    keyed = lf.with_columns([clean_expr(c).str.to_lowercase().alias(f"__k_{c}") for c in cols])
    parts = [pl.col(f"__k_{c}") for c in cols]
    has_key = pl.all_horizontal([p.is_not_null() for p in parts])
    return keyed.with_columns(
        pl.when(has_key).then(pl.concat_str(parts, separator="||")).otherwise(None).alias("join_key")
    ).drop([f"__k_{c}" for c in cols])

legacy_keyed = add_key(
    scan("legacy_metadata").select(
        pl.col("id").cast(pl.Int64, strict=False),
        clean_expr("document_number").alias("document_number"),
        date_expr("issuance_date").alias("issuance_date"),
    ),
    JOIN_COLS,
)

data_renamed = scan("data_metadata").rename({k: v for k, v in COL_MAP.items()})
data_keyed = add_key(
    data_renamed.select(
        pl.col("id").cast(pl.Int64, strict=False).alias("data_id"),
        clean_expr("document_number").alias("document_number"),
        date_expr("issuance_date").alias("issuance_date"),
    ),
    JOIN_COLS,
)

valid_keys = (
    legacy_keyed.group_by("join_key").agg(pl.len().alias("n_legacy"))
    .join(data_keyed.group_by("join_key").agg(pl.len().alias("n_data")), on="join_key", how="inner")
    .filter((pl.col("join_key").is_not_null()) & (pl.col("n_legacy") == 1) & (pl.col("n_data") == 1))
    .select("join_key")
)

rebuilt_crosswalk = (
    legacy_keyed.join(valid_keys, on="join_key", how="inner")
    .join(data_keyed.join(valid_keys, on="join_key", how="inner"), on="join_key", how="inner")
    .select(pl.col("id").alias("legacy_id"), "data_id", "join_key")
)

crosswalk = scan("crosswalk").select(
    pl.col("legacy_id").cast(pl.Int64, strict=False),
    pl.col("data_id").cast(pl.Int64, strict=False),
    pl.col("join_key"),
)

cw_diff_a = crosswalk.join(rebuilt_crosswalk, on=["legacy_id", "data_id", "join_key"], how="anti").collect()
cw_diff_b = rebuilt_crosswalk.join(crosswalk, on=["legacy_id", "data_id", "join_key"], how="anti").collect()

mapping_summary = pl.DataFrame({
    "check": [
        "legacy metadata rows",
        "data metadata rows",
        "valid one-to-one keys rebuilt",
        "crosswalk rows",
        "crosswalk rows not reproducible",
        "rebuilt rows missing from crosswalk",
    ],
    "value": [
        row_count("legacy_metadata"),
        row_count("data_metadata"),
        rebuilt_crosswalk.select(pl.len()).collect().item(),
        row_count("crosswalk"),
        cw_diff_a.height,
        cw_diff_b.height,
    ],
})
display(mapping_summary)

assert cw_diff_a.height == 0, "Crosswalk có dòng không tái tạo được từ legacy+data join key."
assert cw_diff_b.height == 0, "Có dòng one-to-one rebuilt thiếu trong crosswalk."

# %% [markdown]
# ## 4. Validate merged metadata lineage

# %% [code]
merged_metadata = scan("merged_metadata")

metadata_lineage = pl.DataFrame({
    "check": [
        "merged_metadata rows == legacy_metadata rows",
        "merged ids unique",
        "source=legacy+data equals crosswalk rows",
        "source=legacy equals legacy rows - crosswalk rows",
    ],
    "actual": [
        row_count("merged_metadata"),
        merged_metadata.select(pl.col("id").n_unique()).collect().item(),
        merged_metadata.filter(pl.col("source") == "legacy+data").select(pl.len()).collect().item(),
        merged_metadata.filter(pl.col("source") == "legacy").select(pl.len()).collect().item(),
    ],
    "expected": [
        row_count("legacy_metadata"),
        row_count("merged_metadata"),
        row_count("crosswalk"),
        row_count("legacy_metadata") - row_count("crosswalk"),
    ],
})
metadata_lineage = metadata_lineage.with_columns((pl.col("actual") == pl.col("expected")).alias("pass"))
display(metadata_lineage)
assert metadata_lineage["pass"].all(), "Metadata lineage checks failed."

md("### Sample mapped metadata rows")
sample_ids = crosswalk.head(5)
display(
    merged_metadata.join(sample_ids, left_on="id", right_on="legacy_id", how="inner")
    .select("id", "data_id", "document_number", "title", "issuance_date", "source")
    .collect()
)

# %% [markdown]
# ## 5. Sample merged vs data vs legacy
#
# `id` trong file `merged_*` là `legacy_id`: ID gốc của bảng `legacy` và là ID chuẩn sau merge.
#
# `data_id` là ID cũ của cùng văn bản trong bảng `data`. Hai ID khác nhau vì `legacy` và `data` là hai không gian định danh riêng; không được join trực tiếp bằng `id`. Mapping đúng nằm trong `data_to_legacy_crosswalk.parquet`.

# %% [code]
SAMPLE_N = 3
sample_map = crosswalk.head(SAMPLE_N).collect()

legacy_meta_sample = (
    scan("legacy_metadata")
    .select(
        pl.col("id").cast(pl.Int64, strict=False).alias("legacy_id"),
        pl.col("document_number").alias("legacy_document_number"),
        pl.col("title").alias("legacy_title"),
        pl.col("legal_type").alias("legacy_legal_type"),
        pl.col("issuance_date").alias("legacy_issuance_date"),
    )
)
data_meta_sample = (
    scan("data_metadata")
    .select(
        pl.col("id").cast(pl.Int64, strict=False).alias("data_id"),
        pl.col("so_ky_hieu").alias("data_document_number"),
        pl.col("title").alias("data_title"),
        pl.col("loai_van_ban").alias("data_legal_type"),
        pl.col("ngay_ban_hanh").alias("data_issuance_date"),
    )
)
merged_meta_sample = (
    scan("merged_metadata")
    .select(
        pl.col("id").cast(pl.Int64, strict=False).alias("legacy_id"),
        pl.col("document_number").alias("merged_document_number"),
        pl.col("title").alias("merged_title"),
        pl.col("legal_type").alias("merged_legal_type"),
        pl.col("issuance_date").alias("merged_issuance_date"),
        pl.col("source").alias("merged_source"),
    )
)

sample_metadata_compare = (
    sample_map.lazy()
    .join(legacy_meta_sample, on="legacy_id", how="left")
    .join(data_meta_sample, on="data_id", how="left")
    .join(merged_meta_sample, on="legacy_id", how="left")
    .select(
        "legacy_id", "data_id", "join_key",
        "legacy_document_number", "data_document_number", "merged_document_number",
        "legacy_issuance_date", "data_issuance_date", "merged_issuance_date",
        "legacy_legal_type", "data_legal_type", "merged_legal_type",
        "legacy_title", "data_title", "merged_title", "merged_source",
    )
    .collect()
)
display(sample_metadata_compare)

# %% [code]
def content_preview_expr(col: str, n: int = 700) -> pl.Expr:
    return pl.col(col).cast(pl.Utf8, strict=False).str.replace_all(r"\s+", " ").str.slice(0, n)

legacy_content_sample = scan("legacy_content").select(
    pl.col("id").cast(pl.Int64, strict=False).alias("legacy_id"),
    pl.col("content").str.len_chars().alias("legacy_content_len"),
    content_preview_expr("content").alias("legacy_content_preview"),
)
data_content_sample = scan("data_content").select(
    pl.col("id").cast(pl.Int64, strict=False).alias("data_id"),
    pl.col("content_html").str.len_chars().alias("data_content_len"),
    content_preview_expr("content_html").alias("data_content_preview"),
)
merged_content_sample = scan("merged_content").select(
    pl.col("id").cast(pl.Int64, strict=False).alias("legacy_id"),
    pl.col("source").alias("merged_content_source"),
    pl.col("content").str.len_chars().alias("merged_content_len"),
    content_preview_expr("content").alias("merged_content_preview"),
)

sample_content_compare = (
    sample_map.lazy()
    .join(legacy_content_sample, on="legacy_id", how="left")
    .join(data_content_sample, on="data_id", how="left")
    .join(merged_content_sample, on="legacy_id", how="left")
    .collect()
)
display(sample_content_compare)

# %% [markdown]
# ## 6. Validate merged content lineage
#
# `merged_content.id` giữ legacy ID. Nếu có mapping trong crosswalk thì content ưu tiên `data/content.content_html`; nếu không có thì giữ `legacy/content.content`. Nội dung được clean từ HTML/text trước khi ghi output.

# %% [code]
merged_content_sig = scan("merged_content").select(
    pl.col("id").cast(pl.Int64, strict=False),
    pl.col("source"),
    pl.col("content").str.len_chars().alias("content_len"),
    pl.col("content").hash().alias("content_hash"),
)
legacy_content_raw = scan("legacy_content").select(
    pl.col("id").cast(pl.Int64, strict=False),
    pl.col("content").alias("legacy_content"),
)
data_content_raw = (
    scan("data_content")
    .select(
        pl.col("id").cast(pl.Int64, strict=False).alias("data_id"),
        pl.col("content_html"),
        pl.col("content_html").is_not_null().alias("has_data_content"),
    )
    .unique(subset=["data_id"], keep="first")
)

rebuilt_content_sig = (
    legacy_content_raw
    .join(crosswalk.rename({"legacy_id": "id"}), on="id", how="left")
    .join(data_content_raw, on="data_id", how="left")
    .select(
        "id",
        pl.when(pl.col("has_data_content") == True).then(pl.lit("legacy+data")).otherwise(pl.lit("legacy")).alias("source"),
        pl.coalesce("content_html", "legacy_content")
        .map_elements(preprocess_legal_text, return_dtype=pl.Utf8)
        .alias("rebuilt_content"),
    )
    .select(
        "id",
        "source",
        pl.col("rebuilt_content").str.len_chars().alias("content_len"),
        pl.col("rebuilt_content").hash().alias("content_hash"),
    )
)

content_source_counts = merged_content_sig.group_by("source").agg(pl.len().alias("rows")).collect()
rebuilt_source_counts = rebuilt_content_sig.group_by("source").agg(pl.len().alias("rows_rebuilt")).collect()
display(content_source_counts.join(rebuilt_source_counts, on="source", how="full"))

content_diff_a = merged_content_sig.join(rebuilt_content_sig, on=["id", "source", "content_len", "content_hash"], how="anti").collect()
content_diff_b = rebuilt_content_sig.join(merged_content_sig, on=["id", "source", "content_len", "content_hash"], how="anti").collect()

content_lineage = pl.DataFrame({
    "check": [
        "merged_content rows == legacy_content rows",
        "merged content ids unique",
        "rebuilt content signature rows == merged content rows",
        "merged signatures not reproducible from legacy+data+crosswalk",
        "rebuilt signatures missing from merged_content",
    ],
    "actual": [
        row_count("merged_content"),
        merged_content_sig.select(pl.col("id").n_unique()).collect().item(),
        rebuilt_content_sig.select(pl.len()).collect().item(),
        content_diff_a.height,
        content_diff_b.height,
    ],
    "expected": [
        row_count("legacy_content"),
        row_count("merged_content"),
        row_count("merged_content"),
        0,
        0,
    ],
}).with_columns((pl.col("actual") == pl.col("expected")).alias("pass"))
display(content_lineage)

if content_diff_a.height or content_diff_b.height:
    md("### Content signature diff samples")
    display(content_diff_a.head(5))
    display(content_diff_b.head(5))

assert content_lineage["pass"].all(), "Content lineage checks failed."

# %% [markdown]
# ## 7. Validate merged relationships lineage
#
# `data/relationships` dùng ID của data. Output phải remap cả hai đầu edge qua `crosswalk`, giữ edge khi cả source và target map được, bỏ self-loop, rồi dedup.

# %% [code]
rels = scan("data_relationships").select(
    pl.col("doc_id").cast(pl.Int64, strict=False),
    pl.col("other_doc_id").cast(pl.Int64, strict=False),
    "relationship",
)
src_lookup = crosswalk.select(pl.col("data_id").alias("doc_id"), pl.col("legacy_id").alias("src_legacy_id"))
tgt_lookup = crosswalk.select(pl.col("data_id").alias("other_doc_id"), pl.col("legacy_id").alias("tgt_legacy_id"))

rebuilt_relationships = (
    rels.join(src_lookup, on="doc_id", how="inner")
    .join(tgt_lookup, on="other_doc_id", how="inner")
    .select(
        pl.col("src_legacy_id").alias("doc_id"),
        pl.col("tgt_legacy_id").alias("other_doc_id"),
        "relationship",
    )
    .filter(pl.col("doc_id") != pl.col("other_doc_id"))
    .unique(subset=["doc_id", "other_doc_id", "relationship"])
)
merged_relationships = scan("merged_relationships").select(
    pl.col("doc_id").cast(pl.Int64, strict=False),
    pl.col("other_doc_id").cast(pl.Int64, strict=False),
    "relationship",
)

rel_diff_a = merged_relationships.join(rebuilt_relationships, on=["doc_id", "other_doc_id", "relationship"], how="anti").collect()
rel_diff_b = rebuilt_relationships.join(merged_relationships, on=["doc_id", "other_doc_id", "relationship"], how="anti").collect()

relationship_summary = pl.DataFrame({
    "check": [
        "original data relationships",
        "rebuilt remapped relationships",
        "merged relationships",
        "merged rows not reproducible",
        "rebuilt rows missing from merged",
        "self loops in merged",
    ],
    "value": [
        row_count("data_relationships"),
        rebuilt_relationships.select(pl.len()).collect().item(),
        row_count("merged_relationships"),
        rel_diff_a.height,
        rel_diff_b.height,
        merged_relationships.filter(pl.col("doc_id") == pl.col("other_doc_id")).select(pl.len()).collect().item(),
    ],
})
display(relationship_summary)
assert rel_diff_a.height == 0, "Merged relationships có edge không tái tạo được từ data relationships + crosswalk."
assert rel_diff_b.height == 0, "Có edge rebuilt thiếu trong merged relationships."

# %% [markdown]
# ## 8. Distribution EDA

# %% [code]
def value_counts(name: str, col: str, n: int = 20) -> pl.DataFrame:
    return (
        scan(name)
        .group_by(col)
        .agg(pl.len().alias("count"))
        .with_columns((pl.col("count") / pl.col("count").sum() * 100).round(2).alias("pct"))
        .sort("count", descending=True)
        .head(n)
        .collect()
    )

for col in ["source", "legal_type", "issuing_authority", "effect_status"]:
    if col in scan("merged_metadata").collect_schema().names():
        md(f"### merged_metadata.{col}")
        display(value_counts("merged_metadata", col))

md("### merged_relationships.relationship")
display(value_counts("merged_relationships", "relationship"))

# %% [code]
year_eda = (
    scan("merged_metadata")
    .with_columns(pl.col("issuance_date").cast(pl.Utf8, strict=False).str.slice(0, 4).cast(pl.Int32, strict=False).alias("year"))
    .filter(pl.col("year").is_not_null())
    .group_by("year")
    .agg(pl.len().alias("docs"))
    .sort("year")
    .collect()
)
display(year_eda)

# %% [markdown]
# ## 9. Final proof table

# %% [code]
proof = pl.DataFrame({
    "claim": [
        "Merged metadata lấy legacy làm base",
        "Crosswalk tái tạo đúng từ legacy+data one-to-one join_key",
        "Rows source=legacy+data trong metadata bằng crosswalk",
        "Merged content giữ legacy ID và ưu tiên data content khi mapped",
        "Merged relationships được remap từ data IDs sang legacy IDs",
    ],
    "status": [
        "PASS" if row_count("merged_metadata") == row_count("legacy_metadata") else "FAIL",
        "PASS" if cw_diff_a.height == 0 and cw_diff_b.height == 0 else "FAIL",
        "PASS" if merged_metadata.filter(pl.col("source") == "legacy+data").select(pl.len()).collect().item() == row_count("crosswalk") else "FAIL",
        "PASS" if content_diff_a.height == 0 and content_diff_b.height == 0 else "FAIL",
        "PASS" if rel_diff_a.height == 0 and rel_diff_b.height == 0 else "FAIL",
    ],
})
display(proof)
assert (proof["status"] == "PASS").all(), "Final proof failed."

md("# Kết luận\nTất cả kiểm chứng PASS: 4 file trong `merged` được tái tạo nhất quán từ `legacy` + `data`; crosswalk mapping one-to-one đúng; content và relationships dùng mapping này để remap chính xác.")
