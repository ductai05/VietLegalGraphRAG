import os
import re
import html
import json
import time
import logging
import errno
import logging
import shutil
import zipfile
import gc
import sys
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from tqdm import tqdm 
import warnings
warnings.filterwarnings('ignore')

import polars as pl
import pandas as pd
import numpy as np

# ============================================================
# Stable schema for chunk output (avoid Polars inference errors)
# ============================================================

CHUNK_SCHEMA = {
    "chunk_id": pl.Utf8,
    "doc_id": pl.Int64,
    "source": pl.Utf8,
    "chunk_text": pl.Utf8,
    "contextual_text": pl.Utf8,
    "chunk_type": pl.Utf8,
    # Keep both native list + JSON for maximum compatibility/stability
    "section_path": pl.List(pl.Utf8),
    "section_path_json": pl.Utf8,
    "procedure_name": pl.Utf8,
    "embed": pl.Boolean,
    "keyword_index": pl.Boolean,
    "parent_id": pl.Utf8,
    "prev_chunk_id": pl.Utf8,
    "next_chunk_id": pl.Utf8,
    "token_estimate": pl.Int64,
    "char_count": pl.Int64,
    "table_id": pl.Utf8,
    "raw_table_id": pl.Utf8,
    "summary_of": pl.Utf8,
    "source_table_hash": pl.Utf8,
    "table_columns": pl.List(pl.Utf8),
    "table_columns_json": pl.Utf8,
    "table_summary_schema_json": pl.Utf8,
    "table_strategy": pl.Utf8,
    "answer_source": pl.Utf8,
    "do_not_answer_from_summary": pl.Boolean,
    "quality_flags": pl.List(pl.Utf8),
    "quality_flags_json": pl.Utf8,
    "created_at": pl.Float64,
}


def _to_json_or_none(value):
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def normalize_chunk_record(chunk: dict, doc_id: int) -> dict:
    """
    Normalize per-chunk dict to a stable, primitive schema.

    Why: Polars' `DataFrame(list_of_dicts)` infers schema from early rows; later
    rows with different types (e.g., list/dict vs str) can crash the pipeline.
    """
    # Defensive: ensure doc_id is always Int64
    try:
        doc_id_i64 = int(doc_id)
    except Exception:
        # fallback (shouldn't happen with dataset ids)
        doc_id_i64 = None

    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "doc_id": doc_id_i64,
        "source": str(chunk.get("source") or "unknown"),
        "chunk_text": str(chunk.get("chunk_text") or ""),
        "contextual_text": str(chunk.get("contextual_text") or ""),
        "chunk_type": str(chunk.get("chunk_type") or ""),
        "section_path": (
            [str(x) for x in (chunk.get("section_path") or [])]
            if isinstance(chunk.get("section_path"), list)
            else []
        ),
        "section_path_json": _to_json_or_none(chunk.get("section_path")),
        "procedure_name": (None if chunk.get("procedure_name") is None else str(chunk.get("procedure_name"))),
        "embed": bool(chunk.get("embed")) if chunk.get("embed") is not None else True,
        "keyword_index": bool(chunk.get("keyword_index")) if chunk.get("keyword_index") is not None else True,
        "parent_id": str(chunk.get("parent_id") or ""),
        "prev_chunk_id": (None if chunk.get("prev_chunk_id") is None else str(chunk.get("prev_chunk_id"))),
        "next_chunk_id": (None if chunk.get("next_chunk_id") is None else str(chunk.get("next_chunk_id"))),
        "token_estimate": int(chunk.get("token_estimate") or 0),
        "char_count": int(chunk.get("char_count") or len(str(chunk.get("chunk_text") or ""))),
        "table_id": (None if chunk.get("table_id") is None else str(chunk.get("table_id"))),
        "raw_table_id": (None if chunk.get("raw_table_id") is None else str(chunk.get("raw_table_id"))),
        "summary_of": (None if chunk.get("summary_of") is None else str(chunk.get("summary_of"))),
        "source_table_hash": (None if chunk.get("source_table_hash") is None else str(chunk.get("source_table_hash"))),
        "table_columns": (
            [str(x) for x in (chunk.get("table_columns") or [])]
            if isinstance(chunk.get("table_columns"), list)
            else []
        ),
        "table_columns_json": _to_json_or_none(chunk.get("table_columns") or []),
        "table_summary_schema_json": _to_json_or_none(chunk.get("table_summary_schema")),
        "table_strategy": (None if chunk.get("table_strategy") is None else str(chunk.get("table_strategy"))),
        "answer_source": (None if chunk.get("answer_source") is None else str(chunk.get("answer_source"))),
        "do_not_answer_from_summary": bool(chunk.get("do_not_answer_from_summary", False)),
        "quality_flags": (
            [str(x) for x in (chunk.get("quality_flags") or [])]
            if isinstance(chunk.get("quality_flags"), list)
            else []
        ),
        "quality_flags_json": _to_json_or_none(chunk.get("quality_flags")),
        "created_at": float(chunk.get("created_at") or time.time()),
    }

def _load_chunk_legal_document():
    """Load `chunk_legal_document` from the first existing legal_chunker.py."""
    candidates = [
        Path("/kaggle/input/chunking/legal_chunker.py"),
        (Path(__file__).resolve().parent / "legal_chunker.py") if "__file__" in globals() else (Path.cwd() / "legal_chunker.py"),
        Path("/kaggle/input/datasets/brdh7940/chunking/legal_chunker.py"),
    ]

    for path in candidates:
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location("legal_chunker", str(path))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules["legal_chunker"] = module
            spec.loader.exec_module(module)
            if hasattr(module, "chunk_legal_document"):
                return module.chunk_legal_document
    raise ImportError(
        "Could not load chunk_legal_document from any legal_chunker.py candidate."
    )


chunk_legal_document = _load_chunk_legal_document()

# ========== CẤU HÌNH ==========
_INPUT_BASE_CANDIDATES = [
    Path("/kaggle/input/vietnamese-legal-documents-cleaned/cleaned_data"),
    Path("/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/cleaned_data"),
]

for _base in _INPUT_BASE_CANDIDATES:
    if (_base / "content.parquet").exists():
        BASE_PATH = str(_base)
        break
else:
    BASE_PATH = str(_INPUT_BASE_CANDIDATES[0])

CONTENT_PATH = f"{BASE_PATH}/content.parquet"
META_PATH = f"{BASE_PATH}/metadata.parquet"
REL_PATH = f"{BASE_PATH}/relationships.parquet"

# Thư mục làm việc
WORK_DIR = Path("/kaggle/working/legal_chunking")
RAW_DIR = WORK_DIR / "data/raw"
INTERIM_DIR = WORK_DIR / "data/interim"
PROCESSED_DIR = WORK_DIR / "data/processed"
LOGS_DIR = WORK_DIR / "logs"
DLQ_DIR = WORK_DIR / "dlq"

for d in [RAW_DIR, INTERIM_DIR, PROCESSED_DIR, LOGS_DIR, DLQ_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# File checkpoint & log
CHECKPOINT_FILE = LOGS_DIR / "checkpoint.json"
DLQ_FILE = DLQ_DIR / "failed_documents.parquet"
CHUNKS_OUTPUT = PROCESSED_DIR / "chunks.parquet"
METADATA_OUTPUT = PROCESSED_DIR / "metadata.parquet"
CHUNKS_ZIP = PROCESSED_DIR / "chunks.zip"
METADATA_ZIP = PROCESSED_DIR / "metadata.zip"
DATASET_ZIP = PROCESSED_DIR / "legal_chunking_dataset.zip"
LOG_FILE = LOGS_DIR / "pipeline.log"

# Tham số xử lý
BATCH_SIZE = 10000          # Số văn bản trên mỗi batch
MAX_WORKERS = cpu_count()   # Số tiến trình song song
DOC_TIMEOUT_SEC = 60        # Timeout cho mỗi văn bản
CHUNKING_FUNC = chunk_legal_document   # Hàm chunking có sẵn
ZIP_FREE_SPACE_MARGIN = 512 * 1024**2

# Cấu hình logging
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

def load_checkpoint() -> set:
    """Trả về set các doc_id đã xử lý thành công"""
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("processed_ids", []))
    return set()

def update_checkpoint(processed_ids: List[int]):
    """Ghi nhận danh sách id vừa xử lý xong"""
    existing = load_checkpoint()
    existing.update(processed_ids)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"processed_ids": list(existing)}, f, indent=2)

content = pl.read_parquet(CONTENT_PATH)
relationships = pl.read_parquet(REL_PATH)
metadata = pl.read_parquet(META_PATH)

replacements = {
    r"\s+([,.;:])": r"\1",
    r"\s+Ố": "Ố", r"\s+ÊN": "ÊN", r"\s+Ủ": "Ủ", r"\s+ÀNH": "ÀNH",
    r"\s+Ể": "Ể", r"\s+ỀN": "ỀN", r"\s+Ô I": "ÔI", r"\s+ÔNG": "ÔNG",
    r"\s+ÀI": "ÀI", r"\s+Ế": "Ế", r"\s+ỰNG": "ỰNG", r"\s+ể": "ể",
    r"\s+ăng": "ăng", r"\s+ải": "ải", r"\s+ấp": "ấp", r"\s+ấy": "ấy",
    r"\s+ứng": "ứng", r"\s+yền": "yền", r"\s+ịa": "ịa", r"\s+oạt": "oạt",
    r"\s+ộng": "ộng", r"\s+ơ sở": "ơ sở", r"\s+ếu tố": "ếu tố",
    r"\s+ưng": "ưng", r"\s+Ủy": "Ủy"
}

# Xử lý logic theo hướng Lazy để tối ưu memory và tốc độ
content_lazy = content.lazy()
metadata_lazy = metadata.lazy()
relationships_lazy = relationships.lazy()

# Lọc content trước (tối ưu hóa filter)
content_lazy = content_lazy.filter(pl.col('content').str.len_chars() >= 20)

# Lấy các ID hợp lệ một lần duy nhất
valid_ids = content_lazy.select('id')

# Áp dụng thay thế OCR trực tiếp bằng các hàm native của Polars
for pattern, replacement in replacements.items():
    content_lazy = content_lazy.with_columns(
        pl.col('content').str.replace_all(pattern, replacement)
    )

# Áp dụng .collect() để thực thi toàn bộ pipeline đã tối ưu
content = content_lazy.with_columns(
    pl.col('content').str.strip_chars()
).collect()

metadata = metadata_lazy.filter(
    pl.col('id').is_in(valid_ids.collect().get_column('id'))
).collect()

relationships = relationships_lazy.filter(
    pl.col('doc_id').is_in(valid_ids.collect().get_column('id')) & 
    pl.col('other_doc_id').is_in(valid_ids.collect().get_column('id'))
).collect()

def process_single_document(doc_id: int, text: str, src: str) -> Tuple[int, Optional[List[dict]], Optional[str]]:
    """
    Xử lý một văn bản, trả về (doc_id, chunks_list, error_msg)
    Không dùng metadata ở bước này
    """
    try:
        # Gọi hàm chunking có sẵn, truyền metadata=None
        chunks = CHUNKING_FUNC(doc_id, text, src, doc_metadata=None)
        if not isinstance(chunks, list):
            raise ValueError("Chunking function did not return a list")
        return (doc_id, chunks, None)
    except Exception as e:
        return (doc_id, None, f"Doc {doc_id}: {str(e)}")

def process_batch(batch_docs: List[Tuple[int, str, str]], executor: ProcessPoolExecutor) -> Tuple[List[dict], List[dict]]:
    """
    batch_docs: list of (doc_id, text, source)
    executor: ProcessPoolExecutor dùng chung
    Trả về: (list_chunk_dicts, list_error_dicts)
    """
    all_chunks = []
    all_errors = []
    
    tasks = batch_docs
    
    future_to_doc = {
        executor.submit(process_single_document, doc_id, text, src): doc_id
        for (doc_id, text, src) in tasks
    }
    for future in as_completed(future_to_doc):
        doc_id = future_to_doc[future]
        try:
            _, chunks, err = future.result(timeout=DOC_TIMEOUT_SEC)
            if err is None and chunks is not None:
                for chunk in chunks:
                    chunk["doc_id"] = doc_id
                    chunk["created_at"] = time.time()
                all_chunks.extend(chunks)
            else:
                all_errors.append({
                    "doc_id": doc_id,
                    "error_msg": err,
                    "timestamp": time.time()
                })
        except TimeoutError:
            all_errors.append({
                "doc_id": doc_id,
                "error_msg": f"Doc {doc_id} timeout after {DOC_TIMEOUT_SEC}s",
                "timestamp": time.time()
            })
        except Exception as e:
            all_errors.append({
                "doc_id": doc_id,
                "error_msg": f"Future exception: {str(e)}",
                "timestamp": time.time()
            })
    return all_chunks, all_errors

def get_all_doc_ids() -> List[int]:
    df_lazy = pl.scan_parquet(CONTENT_PATH).select("id")
    return df_lazy.collect().to_series().to_list()


def write_batch_chunks(batch_df: pl.DataFrame, batch_idx: int) -> None:
    """Ghi từng batch ra interim — tránh đọc lại toàn bộ chunks.parquet mỗi lần append."""
    path = INTERIM_DIR / f"chunks_batch_{batch_idx:05d}.parquet"
    batch_df.write_parquet(path, compression="snappy")


def merge_all_chunk_outputs() -> None:
    """Gộp chunks.parquet (run cũ/resume) + interim thành một file duy nhất."""
    interim_files = sorted(INTERIM_DIR.glob("chunks_batch_*.parquet"))
    sources: List[str] = []
    if CHUNKS_OUTPUT.exists():
        sources.append(str(CHUNKS_OUTPUT))
    sources.extend(str(p) for p in interim_files)
    if not sources:
        return
    if len(sources) == 1:
        pl.scan_parquet(sources[0]).collect().write_parquet(CHUNKS_OUTPUT, compression="snappy")
    else:
        pl.concat(
            [pl.scan_parquet(s) for s in sources],
            how="diagonal_relaxed",
        ).collect().write_parquet(CHUNKS_OUTPUT, compression="snappy")
    _cleanup_legacy_interim_chunks()


def validate_chunk_invariants(path: Path) -> Dict[str, int]:
    """Validate production gates that can be checked without loading chunk text."""
    lf = pl.scan_parquet(path)
    raw_ids = (
        lf.filter(pl.col("chunk_type") == "raw_table")
        .select(pl.col("chunk_id").alias("_raw_id"))
        .with_columns(pl.lit(True).alias("_raw_exists"))
    )
    summary_links = (
        lf.filter(pl.col("chunk_type") == "table_summary")
        .select("chunk_id", "raw_table_id")
        .join(raw_ids, left_on="raw_table_id", right_on="_raw_id", how="left")
    )
    checks = {
        "raw_table_embed_true": lf.filter(
            (pl.col("chunk_type") == "raw_table") & pl.col("embed")
        ).select(pl.len()).collect().item(),
        "table_summary_embed_false": lf.filter(
            (pl.col("chunk_type") == "table_summary") & (~pl.col("embed"))
        ).select(pl.len()).collect().item(),
        "table_summary_missing_raw_link": summary_links.filter(
            pl.col("_raw_exists").is_null()
        ).select(pl.len()).collect().item(),
        "table_summary_wrong_answer_source": lf.filter(
            (pl.col("chunk_type") == "table_summary")
            & (
                (pl.col("answer_source").fill_null("") != "raw_table")
                | (~pl.col("do_not_answer_from_summary").fill_null(False))
            )
        ).select(pl.len()).collect().item(),
        "procedure_record_missing_columns": lf.filter(
            (pl.col("chunk_type") == "procedure_record")
            & (pl.col("table_columns").list.len().fill_null(0) == 0)
        ).select(pl.len()).collect().item(),
        "dense_hard_split": lf.filter(
            pl.col("embed") & pl.col("quality_flags").list.contains("hard_char_split")
        ).select(pl.len()).collect().item(),
        "dense_long_prose_ge_10k": lf.filter(
            pl.col("embed") & (pl.col("char_count").fill_null(0) >= 10000)
        ).select(pl.len()).collect().item(),
    }
    logging.info("Chunk invariant violations: %s", checks)
    tqdm.write(f"Chunk invariant violations: {checks}")
    return checks


def _cleanup_legacy_interim_chunks() -> None:
    for path in INTERIM_DIR.glob("chunks_batch_*.parquet"):
        path.unlink(missing_ok=True)


def run_pipeline():
    start_time = time.time()
    processed_ids = load_checkpoint()
    all_doc_ids = get_all_doc_ids()

    # Chạy mới từ đầu: xóa file chunk cũ và interim legacy (nếu có)
    if not processed_ids:
        if CHUNKS_OUTPUT.exists():
            CHUNKS_OUTPUT.unlink()
        _cleanup_legacy_interim_chunks()

    to_process = [doc_id for doc_id in all_doc_ids if doc_id not in processed_ids]
    total_to_process = len(to_process)
    logging.info(
        f"Total documents: {len(all_doc_ids)}, already processed: {len(processed_ids)}, "
        f"remaining: {total_to_process} | batch_size={BATCH_SIZE} max_workers={MAX_WORKERS}"
    )
    
    # Chia batch để tránh quá tải bộ nhớ khi đọc content
    batches = [to_process[i:i+BATCH_SIZE] for i in range(0, total_to_process, BATCH_SIZE)]
    
    total_chunks = 0
    total_errors = 0
    processed_count = 0

    # Tạo một ProcessPoolExecutor dùng chung cho tất cả batch
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        with tqdm(total=total_to_process, desc="Processing legal documents", unit="doc", mininterval=0.2) as pbar:
            for batch_idx, batch_ids in enumerate(batches):
                batch_start = time.time()
                tqdm.write(f"Processing batch {batch_idx+1}/{len(batches)} with {len(batch_ids)} docs")
                
                # Đọc nội dung batch từ content
                content_df = pl.scan_parquet(CONTENT_PATH).filter(pl.col("id").is_in(batch_ids)).collect()
                batch_data = [
                    (row["id"], row["content"] or "", row.get("source") or "unknown")
                    for row in content_df.iter_rows(named=True)
                ]
                
                # Gọi process_batch đã sửa, truyền executor dùng chung
                batch_chunks, batch_errors = process_batch(batch_data, executor)
                
                # Cập nhật thanh tiến trình (mỗi document đã được xử lý xong bên trong process_batch)
                # Ta cần cập nhật số lượng document đã xử lý của batch này
                num_docs_in_batch = len(batch_data)
                pbar.update(num_docs_in_batch)
                processed_count += num_docs_in_batch
                
                # Sau khi batch hoàn tất, append vào file chunks duy nhất
                if batch_chunks:
                    tiny_merged = sum(
                        "tiny_chunk_merged" in (c.get("quality_flags") or [])
                        for c in batch_chunks
                    )
                    tiny_filtered = sum(
                        "tiny_chunk_no_dense" in (c.get("quality_flags") or [])
                        for c in batch_chunks
                    )
                    logging.info(
                        "Batch %s tiny handling: merged=%s dense_filtered=%s",
                        batch_idx + 1, tiny_merged, tiny_filtered,
                    )
                    normalized_chunks = [normalize_chunk_record(c, c.get("doc_id")) for c in batch_chunks]
                    chunk_df = pl.DataFrame(normalized_chunks, schema=CHUNK_SCHEMA, strict=False)
                    write_batch_chunks(chunk_df, batch_idx)
                    total_chunks += len(batch_chunks)
                    del normalized_chunks, chunk_df
                
                if batch_errors:
                    error_df = pl.DataFrame(batch_errors)
                    if DLQ_FILE.exists():
                        existing = pl.scan_parquet(DLQ_FILE).collect()
                        error_df = pl.concat([existing, error_df], how="vertical_relaxed")
                    error_df.write_parquet(DLQ_FILE)
                    total_errors += len(batch_errors)
                    del error_df
                
                # Cập nhật checkpoint (chỉ những doc thành công)
                failed_in_batch = {e["doc_id"] for e in batch_errors}
                successful_ids = [doc_id for doc_id in batch_ids if doc_id not in failed_in_batch]
                update_checkpoint(successful_ids)
                
                batch_time = time.time() - batch_start
                n_chunks_batch = len(batch_chunks) if batch_chunks else 0
                n_errors_batch = len(batch_errors)
                tqdm.write(
                    f"Batch {batch_idx+1} done in {batch_time:.2f}s | "
                    f"Chunks: {n_chunks_batch} | Errors: {n_errors_batch}"
                )
                pbar.set_postfix(chunks=total_chunks, failed=total_errors)

                del batch_data, content_df, batch_chunks, batch_errors
                gc.collect()
    
    merge_all_chunk_outputs()
    if CHUNKS_OUTPUT.exists():
        validate_chunk_invariants(CHUNKS_OUTPUT)
    elapsed = time.time() - start_time
    tqdm.write(f"=== PIPELINE FINISHED ===")
    tqdm.write(f"Time: {elapsed:.2f}s | Processed docs: {processed_count - total_errors} | Failed docs: {total_errors} | Total chunks: {total_chunks}")
    logging.info(f"Pipeline finished in {elapsed:.2f}s")
    return total_chunks, total_errors, elapsed

# Chạy pipeline
total_chunks, total_errors, elapsed = run_pipeline()

def _write_dataset_zip_if_space(parquet_paths: Tuple[Path, ...]) -> bool:
    """Create the optional ZIP only when the working disk has enough space."""
    DATASET_ZIP.unlink(missing_ok=True)

    source_size = sum(path.stat().st_size for path in parquet_paths)
    required_free = source_size + ZIP_FREE_SPACE_MARGIN
    free_space = shutil.disk_usage(DATASET_ZIP.parent).free

    if free_space < required_free:
        logging.warning(
            "Skipping ZIP: need about %.2f GiB free but only %.2f GiB is "
            "available. Parquet outputs remain at %s.",
            required_free / 1024**3,
            free_space / 1024**3,
            PROCESSED_DIR,
        )
        return False

    try:
        # Parquet is already compressed. Storing it avoids expensive,
        # low-yield recompression and makes the space estimate predictable.
        with zipfile.ZipFile(
            DATASET_ZIP,
            "w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as zf:
            for path in parquet_paths:
                zf.write(path, arcname=path.name)
    except OSError as exc:
        DATASET_ZIP.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            logging.warning(
                "ZIP creation stopped because the disk became full. "
                "Partial ZIP removed; Parquet outputs remain at %s.",
                PROCESSED_DIR,
            )
            return False
        raise

    logging.info("Zip written: %s", DATASET_ZIP.name)
    return True


def finalize_processed_tables() -> Tuple[Optional[pl.LazyFrame], Optional[pl.LazyFrame]]:
    """
    Xuất metadata riêng và zip mà không nạp toàn bộ parquet vào RAM.
    FK: chunks.doc_id -> metadata.id
    """
    interim_files = sorted(INTERIM_DIR.glob("chunks_batch_*.parquet"))
    if interim_files:
        chunk_sources = [str(path) for path in interim_files]
    elif CHUNKS_OUTPUT.exists():
        with CHUNKS_OUTPUT.open("rb") as parquet_file:
            parquet_file.seek(-4, 2)
            if parquet_file.read(4) != b"PAR1":
                raise RuntimeError(
                    f"Corrupted parquet: {CHUNKS_OUTPUT}. "
                    f"No valid interim files found in {INTERIM_DIR}."
                )
        chunk_sources = [str(CHUNKS_OUTPUT)]
    else:
        logging.warning("No chunks file found. Run pipeline first.")
        return None, None

    chunks_lf = pl.scan_parquet(chunk_sources)
    if interim_files:
        chunks_lf.sink_parquet(CHUNKS_OUTPUT, compression="snappy")
        with CHUNKS_OUTPUT.open("rb") as parquet_file:
            parquet_file.seek(-4, 2)
            if parquet_file.read(4) != b"PAR1":
                raise RuntimeError(f"Failed to create valid parquet: {CHUNKS_OUTPUT}")
        for path in interim_files:
            path.unlink()
        logging.info("Removed %s merged interim chunk files.", len(interim_files))
        chunks_lf = pl.scan_parquet(CHUNKS_OUTPUT)

    chunks_count = chunks_lf.select(pl.len()).collect(engine="streaming").item()
    logging.info(f"Chunks table: {chunks_count} rows -> {CHUNKS_OUTPUT}")

    doc_ids_lf = chunks_lf.select(pl.col("doc_id").alias("id")).unique()
    metadata_lf = (
        pl.scan_parquet(META_PATH)
        .join(doc_ids_lf, on="id", how="semi")
    )
    metadata_lf.sink_parquet(METADATA_OUTPUT, compression="snappy")
    metadata_count = (
        pl.scan_parquet(METADATA_OUTPUT)
        .select(pl.len())
        .collect(engine="streaming")
        .item()
    )
    logging.info(f"Metadata table: {metadata_count} rows -> {METADATA_OUTPUT}")

    _write_dataset_zip_if_space((CHUNKS_OUTPUT, METADATA_OUTPUT))

    return chunks_lf, pl.scan_parquet(METADATA_OUTPUT)


chunks_lf, metadata_lf = finalize_processed_tables()
