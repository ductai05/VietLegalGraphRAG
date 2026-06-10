# 📊 Dense Embedding Pipeline - Trạng thái hiện tại

> **Ngày cập nhật:** 2026-06-10  
> **Giai đoạn:** Step 3 - Build Qdrant collection

---

## ✅ Đã hoàn thành

### 1. **KAGGLE_MEMBER.py** (5 members)

- ✔️ Encode distributed documents từ `chunks.parquet` sử dụng model `darklethelong/vnlegal-lal`
- ✔️ Output: 5 member shards directories (`shards_member_1/` → `shards_member_5/`)
- ✔️ Mỗi shard chứa: vectors (`.npy`), payload metadata (`.parquet`), manifest

### 2. **KAGGLE_MERGE.py**

- ✔️ Verify + merge 5 member shards
- ✔️ Repair missing chunks (nếu có)
- ✔️ Build compact FAISS index (`faiss_members/`)
- ✔️ Output: Deduplicated canonical shards + FAISS artifact

**Artifacts hiện có:**

```
member_inputs/
├── shards_member_1/ ... shards_member_5/  ← vectors + payload gốc
├── embed_payload_v0.1.parquet            ← canonical chunk ID set
repair_shards/                             ← repair output (nếu có)
faiss_members/                             ← FAISS index (fallback)
```

---

## ⏳ Còn thiếu (TODO)

### **Step 3: Build Qdrant Server** ⚠️

_Chưa khởi động_

**Công việc:**

1. Setup Qdrant server (`http://localhost:6333`) hoặc cloud Qdrant
2. Chạy `repair_member_shards.py` → rebuild canonical shards (deduplicated, complete)
3. Chạy `build_qdrant.py` → upsert toàn bộ canonical shards vào Qdrant collection
   ```bash
   python build_qdrant.py \
     --shards-dir /data/legal_embedding/canonical_shards \
     --url http://localhost:6333 \
     --collection legal_chunks_dense_v1 \
     --recreate
   ```

**Tài nguyên cần:**

- Persistent server (không dùng Kaggle vì sẽ vượt disk limit ~30GB)
- GPU nếu vẫn có missing chunks (trong repair phase)
- RAM: ~20-30GB cho canonical shards + Qdrant storage

---

### **Step 4-5: Smoke Test + Dense Retrieval Evaluation** ⏳

_Phụ thuộc vào Step 3_

Sau khi Qdrant server chạy:

1. **Smoke test retrieval:** `dense_retrieval.py` → verify rank/score có ý nghĩa
2. **Evaluation:** `evaluate_dense.py` → tính **Recall@10, MRR@10, nDCG@10**
   - So sánh với gold standard từ JSONL eval set
   - Expected NDCG@10 ≈ **0.8488** (model SOTA)

---

## 📋 Thông tin liên quan

| Thông tin            | Giá trị                                                                                                             |
| -------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Model**            | `darklethelong/vnlegal-lal`                                                                                         |
| **Embedding dim**    | 1024                                                                                                                |
| **Similarity**       | Cosine (L2 normalized)                                                                                              |
| **Max chunk length** | 1024 tokens                                                                                                         |
| **Excluded chunks**  | `raw_table`, `hard_char_split`, `embed=False`                                                                       |
| **Query prefix**     | `"Instruct: Given a Vietnamese legal question, retrieve relevant legal passages that answer the question\nQuery: "` |
| **Important**        | Query prefix chỉ dùng lúc **retrieval**, KHÔNG dùng khi index                                                       |

---

## 🔧 Kế tiếp

**Người phụ trách:** Chỉ định ai setup Qdrant server + chạy Step 3

**Timeline:**

- Step 3 setup: ~1-2 ngày setup infrastructure
- Step 3 upsert: ~2-3 giờ upsert toàn bộ shards (phụ thuộc Qdrant performance)
- Step 4-5: ~30 phút smoke test + evaluation

---

## 📚 File tham khảo

- `PLAN_EMBEDDING.md` - Chi tiết kỹ thuật từng step
- `README.md` - Mô tả file + dependency
- `README_AFTER_KAGGLE_MEMBER.md` - Hướng dẫn hand-off + build Qdrant
- `requirements.txt` - Dependency pipeline
