import os
import re
import html
import json
import time
import logging
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
        "quality_flags": (
            [str(x) for x in (chunk.get("quality_flags") or [])]
            if isinstance(chunk.get("quality_flags"), list)
            else []
        ),
        "quality_flags_json": _to_json_or_none(chunk.get("quality_flags")),
        "created_at": float(chunk.get("created_at") or time.time()),
    }

# Tạo liên kết ảo trỏ đến file đã đổi tên
if not os.path.exists("legal_chunker.py"):
    os.symlink("/kaggle/input/datasets/brdh7940/chunking/legal_chunker.py", "legal_chunker.py")

# Import sạch sẽ không lo xung đột hệ thống
from legal_chunker import chunk_legal_document

# ========== CẤU HÌNH ==========
BASE_PATH = "/kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned"
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
FINAL_CHUNKS_PATTERN = PROCESSED_DIR / "chunks_final_*.parquet"
LOG_FILE = LOGS_DIR / "pipeline.log"

# Tham số xử lý
BATCH_SIZE = 10000          # Số văn bản trên mỗi batch
MAX_WORKERS = cpu_count()   # Số tiến trình song song
DOC_TIMEOUT_SEC = 60        # Timeout cho mỗi văn bản
CHUNKING_FUNC = chunk_legal_document   # Hàm chunking có sẵn

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

def run_pipeline():
    start_time = time.time()
    processed_ids = load_checkpoint()
    all_doc_ids = get_all_doc_ids()
    
    to_process = [doc_id for doc_id in all_doc_ids if doc_id not in processed_ids]
    total_to_process = len(to_process)
    logging.info(f"Total documents: {len(all_doc_ids)}, already processed: {len(processed_ids)}, remaining: {total_to_process}")
    
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
                
                # Sau khi batch hoàn tất, ghi kết quả ra file
                if batch_chunks:
                    normalized_chunks = [normalize_chunk_record(c, c.get("doc_id")) for c in batch_chunks]
                    chunk_df = pl.DataFrame(normalized_chunks, schema=CHUNK_SCHEMA, strict=False)
                    interim_file = INTERIM_DIR / f"chunks_batch_{batch_idx:04d}.parquet"
                    chunk_df.write_parquet(interim_file)
                    total_chunks += len(batch_chunks)
                
                if batch_errors:
                    error_df = pl.DataFrame(batch_errors)
                    if DLQ_FILE.exists():
                        existing = pl.read_parquet(DLQ_FILE)
                        error_df = pl.concat([existing, error_df])
                    error_df.write_parquet(DLQ_FILE)
                    total_errors += len(batch_errors)
                
                # Cập nhật checkpoint (chỉ những doc thành công)
                successful_ids = [doc_id for doc_id in batch_ids if doc_id not in [e["doc_id"] for e in batch_errors]]
                update_checkpoint(successful_ids)
                
                batch_time = time.time() - batch_start
                tqdm.write(f"Batch {batch_idx+1} done in {batch_time:.2f}s | Chunks: {len(batch_chunks)} | Errors: {len(batch_errors)}")
                pbar.set_postfix(chunks=total_chunks, failed=total_errors)
    
    elapsed = time.time() - start_time
    tqdm.write(f"=== PIPELINE FINISHED ===")
    tqdm.write(f"Time: {elapsed:.2f}s | Processed docs: {processed_count - total_errors} | Failed docs: {total_errors} | Total chunks: {total_chunks}")
    logging.info(f"Pipeline finished in {elapsed:.2f}s")
    return total_chunks, total_errors, elapsed

# Chạy pipeline
total_chunks, total_errors, elapsed = run_pipeline()