# Kế hoạch Dense Embedding Pipeline — VietLegalGraphRAG

> **Trạng thái hiện tại:** Chunking hoàn thành (`chunks.parquet` đã có).  
> **Vấn đề tồn đọng:** `table_integrity_bad_pct = 39.38%` > gate 10% — **chưa fix**, xử lý bằng cách tách biệt hoàn toàn `raw_table` và `weak_table` khỏi dense index.  
> **Mục tiêu:** Build dense vector index (Qdrant) phục vụ Hybrid RAG.  
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
        │  → vectors: List[np.ndarray] (1024-dim, float16→float32)
        │  → checkpoint mỗi 1000 chunk
        ▼
[Step 3] Qdrant upsert
        │  → Collection: legal_chunks_v1
        │  → PointStruct: (chunk_id, vector, payload)
        ▼
[Step 4] Payload index (filter metadata)
        │  → Tạo index các trường filter trên Qdrant
        ▼
[Step 5] Export snapshot Qdrant → file (Kaggle output)
        │
        ▼
[Step 6] Kiểm tra / smoke test retrieval
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
    max_len: int = 512,      # chunks thường < 2000 chars ≈ 400-600 tokens
    batch_size: int = 32,
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

**Cấu hình batch_size:**

| GPU | Batch size đề xuất | VRAM ước tính |
|---|---|---|
| T4 (16GB) | 32 | ~8-10GB |
| P100 (16GB) | 48 | ~10-12GB |

> Nếu OOM: giảm `batch_size` hoặc dùng `max_len=384`.  
> Chunks prose tối đa ~2500 chars ≈ 600-800 tokens với tokenizer Qwen — safe với `max_len=1024`.

### 3.4. Pipeline encode với checkpoint

```python
import json
import numpy as np
from pathlib import Path

CHECKPOINT_PATH = Path("/kaggle/working/embed_checkpoint.json")
VECTORS_PATH = Path("/kaggle/working/vectors.npy")

def load_checkpoint() -> set:
    if CHECKPOINT_PATH.exists():
        return set(json.loads(CHECKPOINT_PATH.read_text())["done_ids"])
    return set()

def save_checkpoint(done_ids: list):
    CHECKPOINT_PATH.write_text(json.dumps({"done_ids": list(done_ids)}))

def run_embedding_pipeline(payload_df, batch_size=32, save_every=1000):
    done_ids = load_checkpoint()
    
    # Filter chưa xử lý
    todo_df = payload_df.filter(~pl.col("chunk_id").is_in(list(done_ids)))
    texts = todo_df["contextual_text"].to_list()
    chunk_ids = todo_df["chunk_id"].to_list()
    
    results = {}  # chunk_id → vector
    
    for start in tqdm(range(0, len(texts), save_every)):
        batch_texts = texts[start : start + save_every]
        batch_ids = chunk_ids[start : start + save_every]
        
        vectors = encode_batch(batch_texts, is_query=False, batch_size=batch_size)
        
        for cid, vec in zip(batch_ids, vectors):
            results[cid] = vec
        
        done_ids.update(batch_ids)
        save_checkpoint(list(done_ids))
        
        # Interim save (tránh mất nếu crash)
        interim = {**results}
        # Có thể ghi parquet interim ở đây
    
    return results
```

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
COLLECTION_NAME = "legal_chunks_v1"

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
    "issuance_date": str,      # Ngày ban hành (ISO 8601 hoặc "DD/MM/YYYY")
    "effect_status": str,      # Hiệu lực: "Còn hiệu lực", "Hết hiệu lực"
    "linh_vuc": str,           # Lĩnh vực pháp lý
    "nganh": str,              # Ngành

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
        "effect_status": row.get("effect_status") or "",
        "linh_vuc": row.get("linh_vuc") or "",
        "nganh": row.get("nganh") or "",
        "section_path": row.get("section_path") or [],
        "parent_id": row.get("parent_id") or "",
        "raw_table_id": row.get("raw_table_id") or "",
        "procedure_name": row.get("procedure_name") or "",
    }
    return PointStruct(id=point_id, vector=vector, payload=payload)


def upsert_all(payload_df, vectors_dict: dict):
    rows = payload_df.to_dicts()
    points_batch = []
    
    for row in tqdm(rows):
        cid = row["chunk_id"]
        if cid not in vectors_dict:
            continue
        point = build_point(row, vectors_dict[cid])
        points_batch.append(point)
        
        if len(points_batch) >= UPSERT_BATCH:
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points_batch,
                wait=True,
            )
            points_batch = []
    
    if points_batch:
        client.upsert(collection_name=COLLECTION_NAME, points=points_batch, wait=True)
    
    print(f"Upserted {len(rows)} points to '{COLLECTION_NAME}'")
```

---

## 5. Step 4 — Payload Index cho Metadata Filter

Tạo index trên Qdrant để pre-filter nhanh (không scan toàn collection):

```python
from qdrant_client.models import PayloadSchemaType

# Filter fields — tạo index
index_fields = {
    "effect_status":      PayloadSchemaType.KEYWORD,
    "legal_type":         PayloadSchemaType.KEYWORD,
    "issuing_authority":  PayloadSchemaType.KEYWORD,
    "linh_vuc":           PayloadSchemaType.KEYWORD,
    "nganh":              PayloadSchemaType.KEYWORD,
    "chunk_type":         PayloadSchemaType.KEYWORD,
    "doc_id":             PayloadSchemaType.INTEGER,
    "issuance_date":      PayloadSchemaType.KEYWORD,  # range filter dùng string sort
}

for field, schema in index_fields.items():
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name=field,
        field_schema=schema,
    )
```

### 5.1. Ví dụ filter query khi retrieve

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

# Chỉ tìm trong văn bản còn hiệu lực, lĩnh vực Lao động
filter_condition = Filter(
    must=[
        FieldCondition(
            key="effect_status",
            match=MatchValue(value="Còn hiệu lực"),
        ),
        FieldCondition(
            key="linh_vuc",
            match=MatchValue(value="Lao động"),
        ),
    ]
)

results = client.search(
    collection_name=COLLECTION_NAME,
    query_vector=query_vector,   # encode query với QUERY_PREFIX
    query_filter=filter_condition,
    limit=10,
    with_payload=True,
)
```

---

## 6. Step 5 — Export Snapshot (Kaggle Output)

Kaggle sessions không persist `/kaggle/working/` sang notebook mới. Export Qdrant collection:

```python
# Option A: Export toàn bộ Qdrant storage folder
import shutil
shutil.make_archive(
    "/kaggle/working/qdrant_legal_chunks_v1",
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

> **Khuyến nghị:** Export cả hai — Qdrant snapshot (để load nhanh) và Parquet vector (để rebuild hoặc migrate).

### 6.1. Cấu trúc thư mục output trên Kaggle

```text
/kaggle/working/
  legal_embedding/
    data/
      embed_payload.parquet     # chunk + payload đã join (embed=True)
      vectors.npy               # raw vectors (N × 1024, float32)
      chunk_id_index.json       # chunk_id → row index trong vectors.npy
    qdrant/
      qdrant_storage/           # Qdrant local disk
      qdrant_legal_chunks_v1.zip
    logs/
      embed_checkpoint.json     # resume support
      embed_run.log
```

---

## 7. Step 6 — Expansion Logic (Dense Side)

Sau khi retrieve top-k, thực hiện expand context theo rule:

| chunk_type retrieved | Expansion action | Nguồn |
|---|---|---|
| `clause_group` | Pull `parent_id` (article) nếu score < threshold hoặc `char_count` < 300 | Lookup `chunks.parquet` theo `parent_id` |
| `table_summary` | **Bắt buộc** pull `raw_table_id` → lấy `chunk_text` của `raw_table` | `raw_table` chunk từ `chunks.parquet` hoặc BM25 |
| `procedure_record` | Pull `parent_id` (appendix/article) và `raw_table_id` | Context đủ để hiểu cột |
| `article` | Giữ nguyên, không expand | — |
| `appendix_text` | Pull `parent_id` nếu cần heading context | Lookup |

**Quan trọng về `raw_table` expand:**

```python
# raw_table: KHÔNG đưa vào re-rank hay similarity scoring
# Chỉ dùng để RENDER ANSWER (hiển thị bảng đầy đủ cho user)
# Flow đúng:
# 1. retrieve top-k qua Qdrant (dense, không có raw_table)
# 2. nếu chunk_type == "table_summary": lấy raw_table_id
# 3. fetch raw_table từ BM25 index hoặc chunks.parquet bằng ID lookup
# 4. render raw_table trong context → LLM generate answer
# 5. KHÔNG pass raw_table vào cross-encoder reranker
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
| 3 | Batch encode toàn bộ embed chunks (checkpoint mỗi 1000) | **~30-90 phút** (tùy corpus size) |
| 4 | Khởi tạo Qdrant collection, tạo payload index | 1 phút |
| 5 | Batch upsert vectors + payload vào Qdrant | 10-20 phút |
| 6 | Smoke test: 5 câu hỏi mẫu, verify top-3 results | 5 phút |
| 7 | Export snapshot + vectors.npy → Kaggle output | 5 phút |

---

## 10. Smoke Test Checklist

Sau khi upsert xong, chạy kiểm tra:

```python
TEST_QUERIES = [
    "Hợp đồng lao động gồm những loại nào?",
    "Thủ tục đăng ký khai sinh như thế nào?",
    "Mức phạt vi phạm hành chính về xây dựng không phép?",
    "Điều kiện để được cấp giấy phép kinh doanh dịch vụ du lịch?",
    "Quy định về thời giờ làm việc bình thường?",
]

for q in TEST_QUERIES:
    q_vec = encode_batch([q], is_query=True)[0]
    hits = client.search(COLLECTION_NAME, query_vector=q_vec, limit=3, with_payload=True)
    for h in hits:
        print(f"  score={h.score:.4f} | {h.payload['chunk_type']} | {format_citation(h.payload)}")
    print()
```

**Kỳ vọng:** Top-3 phải thuộc `article`, `clause_group`, `procedure_record`, hoặc `table_summary`. Không được có `raw_table` hay `signature` trong kết quả.

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
# Guard khi build embed_df
def is_safe_to_embed(row: dict) -> bool:
    if not row["embed"]:
        return False
    if row["chunk_type"] == "raw_table":
        return False
    # table_summary: cho embed nhưng phải có raw_table_id
    if row["chunk_type"] == "table_summary" and not row.get("raw_table_id"):
        return False  # hoặc log warning và skip
    return True
```

---

## 12. Doc Handoff cho BM25 Team

### 12.1. Payload schema chung

Xem Section 4.3. BM25 team dùng cùng field names để fusion/RRF sau này.

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

### 12.3. Interface fusion

Dense side trả về:

```python
# Output format từ dense retriever
List[Tuple[str, float]]  # (chunk_id, cosine_score)

# Example:
[
    ("chunk_abc123", 0.912),
    ("chunk_def456", 0.887),
    ("chunk_ghi789", 0.854),
]
```

BM25 team dùng `chunk_id` để fusion/RRF với BM25 scores.

### 12.4. Expansion request interface

Khi dense side cần raw_table:

```python
# Dense request: "tôi cần raw_table của chunk này"
def request_raw_table(raw_table_id: str) -> str:
    """Fetch chunk_text của raw_table từ chunks.parquet hoặc BM25 store."""
    # BM25 team có thể expose API này
    # Hoặc dense side tự lookup chunks.parquet (join trực tiếp)
    pass
```

---

## 13. Dependencies & Environment

```bash
# Kaggle notebook — cell đầu tiên
!pip install -q qdrant-client transformers accelerate torch sentencepiece
```

```python
# Versions đề xuất
qdrant-client >= 1.7.0
transformers >= 4.40.0
torch >= 2.1.0
accelerate >= 0.27.0
polars >= 0.20.0
```

---

## 14. Rủi ro và Mitigation

| Rủi ro | Xác suất | Mitigation |
|---|---|---|
| OOM khi encode batch lớn | Trung bình | Giảm batch_size xuống 16, max_len xuống 512 |
| Kaggle session timeout (9h) | Thấp | Checkpoint mỗi 1000 chunks, resume tự động |
| `contextual_text` thiếu metadata prefix | Cao | Rebuild contextual_text với metadata.parquet trước khi encode |
| Qdrant disk full | Thấp | 1M × 1024 × 4 bytes ≈ 4GB — safe trong 20GB Kaggle |
| `raw_table_id` không resolve | Trung bình (39.38% table issue) | Log warning, skip expand, không crash |
| Vector distribution shift khi re-embed v0.2 | Tương lai | Version collection: `legal_chunks_v1`, `legal_chunks_v2` |

---

## 15. Kết quả kỳ vọng sau Phase 4

| Metric | Target |
|---|---|
| Số chunks được embed | Tất cả `embed=True` trong chunks.parquet |
| Qdrant collection size | Theo corpus (ước tính 500K-2M points) |
| Vector dim | 1024 |
| Smoke test top-3 relevance | Phải trả về chunk thuộc loại article/clause_group/procedure_record |
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

*Tài liệu này là kế hoạch trước khi implement. Cập nhật sau khi chạy Kaggle notebook.*
