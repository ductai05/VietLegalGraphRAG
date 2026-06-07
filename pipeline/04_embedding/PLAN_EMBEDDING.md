# Kế hoạch Dense Embedding Pipeline — VietLegalGraphRAG

> **Trạng thái hiện tại:** Chunking hoàn thành (`chunks.parquet` đã có).  
> **Vấn đề tồn đọng:** `table_integrity_bad_pct = 39.38%` > gate 10% — **chưa fix**, xử lý bằng cách tách biệt hoàn toàn `raw_table` và `weak_table` khỏi dense index.  
> **Mục tiêu:** Build **dense retriever component** (Qdrant) cho hybrid fusion sau này — không implement BM25/hybrid.  
> **Output:** `DenseResult = {chunk_id, dense_score, payload, optional_expanded_context}`  
> **Platform:** Kaggle (GPU T4/P100).  
> **Embedding model:** [`darklethelong/vnlegal-lal`](https://huggingface.co/darklethelong/vnlegal-lal) — 600M params, 1024-dim, NDCG@10 = 0.8488.

---

## 0. Tổng quan pipeline

```
chunks.parquet + metadata.parquet
        │
        ▼
[Step 1] Pre-embedding filter & join
        │  → embed_df: chỉ chunk embed=True, loại raw_table
        │  → payload_df: join metadata (doc_id → title, legal_type, ...)
        ▼
[Step 2] Batch encoding với VNLegal-LAL
        │  → save theo shard: vectors_shard_NNN.npy + payload_shard_NNN.parquet
        │  → manifest.json sau khi shard ghi xong
        ▼
[Step 3] Qdrant: create collection → payload index → upsert theo shard
        │  → Collection: legal_chunks_dense_v1
        ▼
[Step 4] Export snapshot Qdrant → file (Kaggle output)
        ▼
[Step 5] Smoke test retrieval
        ▼
[Step 6b] Dense retrieval evaluation (Recall@10, MRR@10, nDCG@10)
```

---

## 1. Thông tin Embedding Model

| Thuộc tính | Giá trị |
|---|---|
| **Model ID** | `darklethelong/vnlegal-lal` |
| **Base model** | `mainguyen9/vietlegal-harrier-0.6b` (Qwen3) |
| **Kiến trúc** | Decoder-only Transformer |
| **Params** | 600M |
| **Dim** | 1024 |
| **Max seq length** | 2048 tokens |
| **Pooling** | Last-token |
| **Normalize** | L2 (built-in trong SentenceTransformer) |
| **Similarity** | Cosine |
| **License** | Apache 2.0 |
| **NDCG@10** | **0.8488** (SOTA Zalo AI Legal Text Retrieval) |

### 1.1. Query prefix (chỉ dùng khi retrieve, KHÔNG dùng khi index)

```python
QUERY_PREFIX = "Instruct: Given a Vietnamese legal question, retrieve relevant legal passages that answer the question\nQuery: "
```

**Quan trọng:** Document được encode **không có prefix**. Prefix chỉ prepend cho **query** lúc retrieval.

### 1.2. Cách dùng đúng

```python
# Index time: encode document (contextual_text)
doc_embs = encode(texts, is_query=False)

# Query time: encode question
query_embs = encode([question], is_query=True)
# → tự prepend QUERY_PREFIX bên trong hàm encode()
```

---

## 2. Step 1 — Pre-embedding Filter & Join

### 2.1. Tập chunk được embed (dense index)

Filter theo **tất cả** điều kiện sau:

```python
embed_df = (
    chunks_df
    .filter(pl.col("embed") == True)
    # raw_table luôn có embed=False (do chunker set), nhưng guard thêm cho chắc
    .filter(pl.col("chunk_type") != "raw_table")
    # Loại các chunk bị hard_char_split (cắt cơ học, embed=False đã set)
    # Dòng dưới chỉ để verify — embed=False đã loại ở trên
    # .filter(~pl.col("quality_flags").list.contains("hard_char_split"))
)
```

**Lý do loại trừ:**

| Loại chunk | Lý do không embed |
|---|---|
| `raw_table` | `table_integrity_bad_pct = 39.38%` — header missing, retrieval vô nghĩa |
| `embed=False` | Chunker đã đánh dấu: hard_char_split, tiny_chunk_no_dense, long_prose ≥ 10k, signature, distribution_list |
| `quality_flags` chứa `hard_char_split` | Cắt cơ học giữa câu — context không đủ nghĩa |

**Các `chunk_type` sẽ có trong dense index:**

| chunk_type | embed | Ghi chú |
|---|---|---|
| `article` | ✅ | Điều/khoản chính |
| `clause_group` | ✅ | Nhóm khoản từ Điều dài |
| `appendix_text` | ✅ | Phụ lục có cấu trúc luật |
| `procedure_record` | ✅ | Một thủ tục hành chính |
| `table_summary` | ✅ | Mô tả bảng lớn (expand → raw_table để answer) |
| `table` | ✅ (nếu embed=True) | Bảng nhỏ/trung bình |
| `table_part` | ✅ (nếu embed=True) | Row-level bảng, chỉ khi đủ context |
| `preamble` | ✅ | Phần mở đầu |
| `appendix` / `appendix_group` | ✅ | Tiêu đề phụ lục/nhóm |
| `part` / `chapter` / `section` | ✅ (nếu embed=True) | Tiêu đề cấu trúc |
| `short_text` / `fallback_text` | ✅ (nếu embed=True) | Văn bản ngắn/fallback |

### 2.2. Join metadata

```python
# payload_df: mỗi chunk kèm đủ metadata để filter và citation
payload_df = (
    embed_df
    .join(
        metadata_df.select([
            "id",
            "document_number", "title",
            "legal_type", "issuing_authority",
            "issuance_date", "effect_status",
            "linh_vuc", "nganh", "pham_vi",
            "effect_date", "effectless_date",
            # Normalize sang ts (YYYYMMDD int) cho range filter — xem 2.4
        ]),
        left_on="doc_id",
        right_on="id",
        how="left",
    )
)
```

### 2.3. Field dùng để embed

```python
# Dùng contextual_text (đã có prefix metadata + section_path từ chunker)
# Format: "[Văn bản: ... | Cơ quan: ... | Ngày: ... | Mục: ...]\n\n<chunk_text>"
text_to_embed = payload_df["contextual_text"].to_list()
```

> **Lưu ý:** `batch_chunk.py` không inject metadata vào `contextual_text` (doc_metadata=None).  
> Nếu `contextual_text` chỉ có `section_path`, rebuild trước khi embed:
>
> ```python
> # Rebuild contextual_text với đầy đủ metadata
> def rebuild_contextual_text(row):
>     parts = []
>     if row["title"]: parts.append(f"Văn bản: {row['document_number']} - {row['title']}")
>     if row["issuing_authority"]: parts.append(f"Cơ quan: {row['issuing_authority']}")
>     if row["issuance_date"]: parts.append(f"Ngày ban hành: {row['issuance_date']}")
>     section_str = " > ".join(row["section_path"] or [])
>     if section_str: parts.append(f"Mục: {section_str}")
>     prefix = " | ".join(parts)
>     return f"[{prefix}]\n\n{row['chunk_text']}" if prefix else row["chunk_text"]
> ```

### 2.4. Normalize date fields (range filter)

```python
# Thêm vào payload — index INTEGER trên Qdrant
"issuance_date_ts": int,      # YYYYMMDD
"effect_date_ts": int,
"effectless_date_ts": int | None,
# Giữ issuance_date string gốc cho citation/display
```

---

## 3. Step 2 — Batch Encoding với VNLegal-LAL (Kaggle GPU)

### 3.1. Môi trường Kaggle

```
Kaggle GPU: T4 (16GB VRAM) hoặc P100 (16GB)
RAM: 30GB
Disk: /kaggle/working/ (20GB)
Model size: ~1.2GB (float16)
```

### 3.2. Tải model

```python
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

MODEL_NAME = "darklethelong/vnlegal-lal"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModel.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float16,
    device_map=DEVICE,
)
model.eval()
```

> **Lưu ý Kaggle:** Lần đầu tải ~1.2GB — đặt `TRANSFORMERS_CACHE=/kaggle/working/.cache` hoặc dùng Kaggle Dataset cache.

### 3.3. Hàm encode (document)

```python
QUERY_PREFIX = (
    "Instruct: Given a Vietnamese legal question, "
    "retrieve relevant legal passages that answer the question\nQuery: "
)

def encode_batch(
    texts: list[str],
    is_query: bool = False,
    max_len: int = 1024,     # default production; model support 2048
    batch_size: int = 16,    # T4: bắt đầu 16–24, tăng dần nếu ổn
) -> list[list[float]]:
    """Encode list of texts → list of 1024-dim float vectors."""
    all_embs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        if is_query:
            batch = [QUERY_PREFIX + t for t in batch]
        inputs = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=max_len,
            return_tensors="pt",
        ).to(DEVICE)
        with torch.no_grad():
            out = model(**inputs)
        last_idx = inputs["attention_mask"].sum(dim=1) - 1
        embs = out.last_hidden_state[
            torch.arange(len(batch), device=DEVICE), last_idx
        ]
        embs = F.normalize(embs, p=2, dim=1)
        all_embs.extend(embs.cpu().float().tolist())  # float32 để Qdrant nhận
    return all_embs
```

**`max_len` theo chunk_type:**

| Loại chunk | max_len |
|---|---|
| `article`, `clause_group`, `procedure_record` | 1024 |
| `table_summary`, `preamble`, heading | 512 |
| `appendix_text` / fallback dài | 1024–1536 |
| debug run | 512 |

| GPU | Batch size | VRAM ước tính |
|---|---|---|
| T4 (16GB) | 16–24 | ~8-10GB |
| P100 (16GB) | 24–32 | ~10-12GB |

> Nếu OOM: giảm `batch_size`. Không hạ default `max_len` xuống 512 cho production.

### 3.4. Pipeline encode theo shard (không giữ vectors_dict trong RAM)

```python
SHARD_SIZE = 10_000  # chunks/shard

# Mỗi shard:
# 1. encode
# 2. save vectors_shard_0001.npy  (float16 — không giữ vectors.npy gộp)
# 3. save payload_shard_0001.parquet
# 4. update manifest.json (chỉ mark shard done sau khi file ghi xong)

# manifest.json ghi thêm:
# embedding_model, model_revision, chunker_version, max_len, normalize=True, vector_dtype=float16
```

### 3.5. Storage sizing

Corpus thực tế (`embed=True`): **~5.57M chunks** × 1024 × 4 bytes ≈ **22.8 GB** float32 — `/kaggle/working` 20GB **không đủ** khi cộng payload parquet, Qdrant storage (vector + payload + HNSW), zip snapshot.

| Artifact | Ước tính | Ghi chú |
|---|---|---|
| `vectors_shard_*.npy` (float16) | ~11.4 GB | Archival; convert float32 chỉ lúc upsert |
| `payload_shard_*.parquet` | vài GB | |
| Qdrant local | > raw vectors | Point = vector + payload + index |

**Quy tắc:** không giữ `vectors.npy` gộp; export shard trước; nếu Qdrant full disk → index ngoài Kaggle; cân nhắc split collection theo shard/domain.

---

## 4. Step 3 — Qdrant Setup & Upsert

### 4.1. Cài đặt Qdrant (local trên Kaggle)

```python
# Kaggle: chạy Qdrant server local hoặc dùng in-memory client
# Option A: In-memory (nhanh, không persist giữa sessions)
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

client = QdrantClient(":memory:")

# Option B: Local disk (persist trong /kaggle/working/)
client = QdrantClient(path="/kaggle/working/qdrant_storage")
```

> **Recommended cho Kaggle:** Option B (disk) để có thể export snapshot và dùng lại.

### 4.2. Tạo Collection

```python
COLLECTION_NAME = "legal_chunks_dense_v1"

client.recreate_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(
        size=1024,           # dim của VNLegal-LAL
        distance=Distance.COSINE,
    ),
    # Tối ưu cho dataset ~vài triệu chunks
    hnsw_config={
        "m": 16,
        "ef_construct": 100,
        "full_scan_threshold": 10000,
    },
    optimizers_config={
        "default_segment_number": 4,
    },
)
```

### 4.3. Payload Schema

Mỗi vector point chứa payload sau (để filter và citation):

```python
# Payload fields bắt buộc trên mỗi vector point
{
    # === Chunk identity ===
    "chunk_id": str,           # unique key
    "doc_id": int,             # FK → metadata
    "chunk_type": str,         # article, clause_group, table_summary, ...
    "source": str,             # nguồn (thuvienphapluat, ...)

    # === Metadata văn bản (join từ metadata.parquet) ===
    "document_number": str,    # Số hiệu: "1762/QĐ-UBND"
    "title": str,              # Tên văn bản
    "legal_type": str,         # Loại: Nghị định, Thông tư, ...
    "issuing_authority": str,  # Cơ quan ban hành
    "issuance_date": str,      # Display/citation
    "issuance_date_ts": int,   # YYYYMMDD — range filter
    "effect_date_ts": int,
    "effectless_date_ts": int | None,
    "effect_status": str,
    "expansion_status": str,   # "ok" | "missing_raw_table" (table_summary)
    "linh_vuc": str,           # Lĩnh vực pháp lý
    "nganh": str,              # Ngành

    # === Table multi-vector (README_CHUNKING §7) ===
    "table_id": str,           # Group chunk cùng bảng
    "summary_of": str,         # raw_table_id alias trên table_summary
    "answer_source": str,      # "raw_table" | "procedure_record" — enforce expand
    "do_not_answer_from_summary": bool,  # True trên table_summary
    "table_columns": list[str],  # Nếu không quá dài; procedure/table_part cần hiểu cột
    # source_table_hash → local lookup/debug only
    # table_summary_schema_json → local lookup (payload quá nặng)

    # === Navigation (expand context) ===
    "section_path": list[str], # ["Chương II", "Điều 5"]
    "parent_id": str,          # chunk_id của parent (null nếu không có)
    "raw_table_id": str,       # chunk_id raw_table tương ứng (cho table_summary)

    # === Citation ===
    "procedure_name": str,     # Tên TTHC (chỉ procedure_record)
}
```

### 4.4. Batch Upsert

```python
from qdrant_client.models import PointStruct
import uuid

UPSERT_BATCH = 200  # points per upsert call

def build_point(row: dict, vector: list[float]) -> PointStruct:
    """Chuyển chunk row + vector → Qdrant PointStruct."""
    # Dùng chunk_id string làm id (Qdrant hỗ trợ UUID string)
    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, row["chunk_id"]))
    payload = {
        "chunk_id": row["chunk_id"],
        "doc_id": int(row["doc_id"]),
        "chunk_type": row["chunk_type"] or "",
        "source": row["source"] or "",
        "document_number": row.get("document_number") or "",
        "title": row.get("title") or "",
        "legal_type": row.get("legal_type") or "",
        "issuing_authority": row.get("issuing_authority") or "",
        "issuance_date": row.get("issuance_date") or "",
        "issuance_date_ts": int(row.get("issuance_date_ts") or 0),
        "effect_date_ts": int(row.get("effect_date_ts") or 0),
        "effectless_date_ts": row.get("effectless_date_ts"),
        "expansion_status": row.get("expansion_status") or "ok",
        "effect_status": row.get("effect_status") or "",
        "linh_vuc": row.get("linh_vuc") or "",
        "nganh": row.get("nganh") or "",
        "section_path": row.get("section_path") or [],
        "parent_id": row.get("parent_id") or "",
        "raw_table_id": row.get("raw_table_id") or "",
        "table_id": row.get("table_id") or "",
        "summary_of": row.get("summary_of") or "",
        "answer_source": row.get("answer_source") or "",
        "do_not_answer_from_summary": bool(row.get("do_not_answer_from_summary", False)),
        "table_columns": row.get("table_columns") or [],
        "procedure_name": row.get("procedure_name") or "",
    }
    return PointStruct(id=point_id, vector=vector, payload=payload)


def upsert_shard(payload_shard_path, vectors_shard_path):
    """Upsert từng shard — không load toàn bộ corpus vào RAM."""
    # load payload_shard + vectors_shard (float16 → float32) → batch upsert
    # verify: qdrant_count == len(embed_payload)
    pass
```

### 4.5. Payload index — tạo **trước** upsert

```python
from qdrant_client.models import PayloadSchemaType

index_fields = {
    "doc_id":             PayloadSchemaType.INTEGER,
    "chunk_type":         PayloadSchemaType.KEYWORD,
    "legal_type":         PayloadSchemaType.KEYWORD,
    "issuing_authority":  PayloadSchemaType.KEYWORD,
    "effect_status":      PayloadSchemaType.KEYWORD,
    "linh_vuc":           PayloadSchemaType.KEYWORD,
    "nganh":              PayloadSchemaType.KEYWORD,
    "issuance_date_ts":   PayloadSchemaType.INTEGER,
    "effect_date_ts":     PayloadSchemaType.INTEGER,
}

for field, schema in index_fields.items():
    client.create_payload_index(COLLECTION_NAME, field_name=field, field_schema=schema)
```

**Thứ tự:** create collection → create payload indexes → upsert theo shard.

### 4.6. Dense retrieval API

```python
def dense_search(query: str, filters: dict | None, top_k: int = 20) -> list[DenseHit]:
    """Output: chunk_id, score, doc_id, chunk_type, section_path, title,
    document_number, parent_id, raw_table_id, citation."""
    query_vector = encode_batch([query], is_query=True)[0]
    # Dùng query_points (Qdrant mới) thay vì search
    return client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=build_filter(filters),
        limit=top_k,
        with_payload=True,
    )
```

---

## 5. Step 4 — Export Snapshot (Kaggle Output)

Kaggle sessions không persist `/kaggle/working/` sang notebook mới. Export Qdrant collection:

```python
# Option A: Export toàn bộ Qdrant storage folder
import shutil
shutil.make_archive(
    "/kaggle/working/qdrant_legal_chunks_dense_v1",
    "zip",
    "/kaggle/working/qdrant_storage",
)
# → /kaggle/working/qdrant_legal_chunks_v1.zip → upload lên Kaggle Dataset

# Option B: Export vectors + payload dưới dạng Parquet (portable hơn)
# Có thể dùng để rebuild Qdrant sau
records, _ = client.scroll(
    collection_name=COLLECTION_NAME,
    limit=10000,
    with_vectors=True,
    with_payload=True,
)
# → serialize ra file parquet
```

> **Khuyến nghị:** Export **shard float16 + payload parquet trước** (portable, fit Kaggle output). Qdrant snapshot zip chỉ khi disk đủ; nếu không → build index ngoài Kaggle từ shard export.

### 5.1. Cấu trúc thư mục output trên Kaggle

```text
/kaggle/working/
  legal_embedding/
    data/
      embed_payload_v0.1.parquet
      vectors_shard_000.npy
      payload_shard_000.parquet
      vectors_shard_001.npy
      ...
      manifest.json               # shard status + model metadata
    qdrant/
      qdrant_storage/
      qdrant_legal_chunks_dense_v1.zip
    logs/
      embed_run.log
      table_repair_candidates.parquet
```

---

## 6. Step 5 — Expansion Logic (Dense Side owns lookup)

Build `chunk_lookup` từ `chunks.parquet` — **không phụ thuộc BM25 team** cho expansion.

| chunk_type retrieved | Expansion action |
|---|---|
| `clause_group` | Pull `parent_id` nếu score thấp hoặc chunk ngắn |
| `table_summary` | Pull `raw_table_id` nếu có; enforce `do_not_answer_from_summary=True`, `answer_source` ∈ {raw_table, procedure_record}; nếu thiếu → `expansion_status="missing_raw_table"` |
| `procedure_record` | Pull `parent_id` / `raw_table_id` nếu có |
| `article` | Giữ nguyên |

```python
# raw_table: KHÔNG embed, KHÔNG re-rank — chỉ lookup từ chunks.parquet để render answer
# Log unresolved: missing_parent_id, missing_raw_table_id, weak_table_context
```

### 7.1. Score threshold cho expansion

```python
EXPAND_THRESHOLDS = {
    "clause_group_to_article": 0.75,  # expand nếu score < 0.75
    "clause_group_min_chars": 300,    # expand nếu chunk quá ngắn
}
```

---

## 8. Citation Output Format

Mỗi chunk retrieved phải kèm đủ thông tin để trích dẫn:

```python
def format_citation(payload: dict) -> str:
    """Tạo citation string từ Qdrant payload."""
    parts = []
    if payload.get("document_number"):
        parts.append(payload["document_number"])
    if payload.get("title"):
        parts.append(payload["title"])
    if payload.get("section_path"):
        parts.append(" > ".join(payload["section_path"]))
    if payload.get("procedure_name"):
        parts.append(f"[TTHC: {payload['procedure_name']}]")
    parts.append(f"chunk_id: {payload['chunk_id']}")
    return " | ".join(parts)

# Ví dụ output:
# "1762/QĐ-UBND | Về ban hành Danh mục... | Phụ lục 1 > Điều 3 | chunk_id: abc123"
```

---

## 9. Thứ tự implement trên Kaggle (Notebook cells)

| Cell | Nội dung | Thời gian ước tính |
|---|---|---|
| 0 | Setup: cài `qdrant-client`, `transformers`, `torch`, paths | 2 phút |
| 1 | Load `chunks.parquet` + `metadata.parquet`, filter embed=True, rebuild contextual_text | 3 phút |
| 2 | Load VNLegal-LAL model lên GPU, smoke test encode 5 chunks | 3-5 phút |
| 3 | Batch encode theo shard (10k/shard) | **~30-90 phút** |
| 4 | Qdrant: collection → payload index → upsert shard | 10-20 phút |
| 5 | Smoke test 5 câu | 5 phút |
| 6 | Dense eval: 100–200 query, Recall@10/MRR@10/nDCG@10 | 30 phút |
| 7 | Export snapshot + shards → Kaggle output | 5 phút |

---

## 10. Smoke Test + Dense Evaluation

**Smoke test (5 câu):** verify top-3 không có `raw_table`/`signature`; chunk types hợp lệ.

**Step 6b — Dense Retrieval Evaluation** (bắt buộc trước production):

```text
- Build 100–200 query set, label gold doc_id / chunk_id / article path
- Nhóm: article QA, procedure QA, table summary QA, metadata-filter QA
- Report: Recall@5/10, MRR@10, nDCG@10
- Split: Recall@10 by chunk_type (article, clause_group, procedure_record, table_summary)
- filter success rate, expansion success rate, citation correctness
```

---

## 11. Xử lý table_integrity_bad_pct = 39.38% (hiện tại)

Do `table_integrity_bad_pct = 39.38%` vượt gate (< 10%), cần các biện pháp bảo vệ:

| Hành động | Mô tả |
|---|---|
| **Không embed `raw_table`** | Đã xử lý: `embed=False` từ chunker |
| **Chỉ embed `table_summary`** | table_summary đã có rule-based text, ít bị ảnh hưởng |
| **`do_not_answer_from_summary=True`** | Bắt buộc expand sang `raw_table` để trả lời số liệu |
| **Warn trong citation** | Nếu `raw_table_id` không resolve → log warning, không crash |
| **Phase 4 (sau)** | Sau khi fix table repair, rebuild `chunks_v0.2`, re-embed phần bảng |

```python
# table_summary thiếu raw_table_id: VẪN embed nếu summary text tốt
# → set expansion_status="missing_raw_table", log vào table_repair_candidates.parquet
# → không dùng cho answer exact values

# Validate trước embed (table_summary):
if chunk_type == "table_summary":
    assert do_not_answer_from_summary is True
    assert answer_source in ("raw_table", "procedure_record")
# table_summary_schema_json, source_table_hash → chunk_lookup local, không đưa Qdrant payload
```

---

## 12. Interface Contract cho BM25 Team (không phải trách nhiệm implement)

### 12.1. Payload schema chung

Xem Section 4.3. Cùng `chunk_id` namespace để fusion/RRF sau này.

### 12.2. Chunks KHÔNG có trong dense index

Dense side **không index** các chunk sau (BM25 team tự quyết):

| chunk_id pattern | chunk_type | Lý do dense skip |
|---|---|---|
| `*` với `embed=False` | Mọi loại | Chunker flag: hard_split, tiny_no_dense, prose≥10k |
| `raw_table` type | `raw_table` | table_integrity 39.38% — cần Phase 4 fix |
| `signature` | `signature` | Không có nội dung pháp lý |
| `distribution_list` | `distribution_list` | Không có nội dung pháp lý |

```python
# BM25 team: filter chunk_type NOT IN ('signature', 'distribution_list')
# và keyword_index=True
bm25_df = chunks_df.filter(
    pl.col("keyword_index") == True
)
# raw_table: BM25 CÓ THỂ index (keyword search trên bảng raw vẫn hữu ích)
```

### 12.3. Fusion interface

```python
DenseResult = {
    "chunk_id": str,
    "dense_score": float,
    "payload": dict,
    "optional_expanded_context": str | None,
}
```

Dense side owns expansion lookup từ `chunks.parquet`. BM25 team chỉ cần cùng `chunk_id` namespace.

---

## 13. Dependencies & Environment

```bash
# Kaggle notebook — PyTorch cài riêng theo GPU; xem README
!pip install -q -r requirements.txt
```

```python
# Versions đề xuất
qdrant-client >= 1.7.0, < 2
transformers >= 4.51.0, < 5
polars >= 0.20.0, < 2
```

---

## 14. Rủi ro và Mitigation

| Rủi ro | Xác suất | Mitigation |
|---|---|---|
| OOM khi encode batch lớn | Trung bình | Giảm batch_size; giữ max_len=1024 cho article/clause |
| Kaggle session timeout (9h) | Thấp | Shard checkpoint; resume từ manifest.json |
| Crash giữa encode → mất vector | Trung bình | Chỉ mark shard done sau khi .npy + .parquet ghi xong |
| `contextual_text` thiếu metadata prefix | Cao | Rebuild contextual_text với metadata.parquet trước khi encode |
| Qdrant disk full | **Cao** | ~5.57M × 1024 × 4 ≈ 22.8GB float32 + payload + HNSW > 20GB Kaggle; lưu shard float16 (~11.4GB), upsert/index ngoài Kaggle nếu cần |
| `raw_table_id` không resolve | Trung bình (39.38% table issue) | Log warning, skip expand, không crash |
| Vector distribution shift khi re-embed v0.2 | Tương lai | Version collection: `legal_chunks_dense_v1`, `legal_chunks_dense_v2` |

---

## 15. Kết quả kỳ vọng sau Phase 4

| Metric | Target |
|---|---|
| Số chunks được embed | Tất cả `embed=True` trong chunks.parquet |
| Qdrant collection size | ~5.57M points (`embed=True`); Qdrant storage > 22.8GB raw vectors |
| Vector dim | 1024 |
| Dense eval nDCG@10 | Baseline trên 100–200 query labeled |
| Smoke test top-3 relevance | article/clause_group/procedure_record/table_summary |
| Filter latency | < 50ms (với payload index) |
| Encode throughput | ~100-200 chunks/s trên T4 GPU (batch 32) |

---

## 16. Phase tiếp theo (sau Dense Embedding)

1. **BM25 indexing** — đồng bộ với dense team theo schema Section 12
2. **Hybrid fusion (RRF)** — kết hợp dense + BM25 scores
3. **Reranker** — cross-encoder rerank top-30 → top-5
4. **LightRAG / GraphRAG** — `relationships.parquet` + `parent_id` chain
5. **Table repair (Phase 4)** — fix `table_integrity_bad_pct`, re-embed `chunks_v0.2`
6. **End-to-end evaluation** — NDCG@10 trên tập query pháp lý Việt Nam

---

## 17. Task List (condensed)

| Phase | Tasks |
|---|---|
| **A — Data freeze** | Freeze `chunks_v0.1.parquet` → `embed_payload_v0.1.parquet`; filter embed=True, ≠raw_table; rebuild contextual_text; normalize date ts |
| **B — Embedding** | VNLegal-LAL; doc=no prefix, query=prefix; max_len=1024; shard save float16 + manifest |
| **C — Qdrant** | `legal_chunks_dense_v1`; index trước ingest; upsert shard (float16→float32); verify count; fallback index ngoài Kaggle nếu disk full |
| **D — API** | `dense_search()` → DenseHit với citation fields |
| **E — Expansion** | chunk_lookup local; log unresolved expansion |
| **F — Eval** | 100–200 query; Recall@10, MRR@10, nDCG@10 by chunk_type |

---

*Tài liệu này là kế hoạch trước khi implement. Cập nhật sau khi chạy Kaggle notebook.*
