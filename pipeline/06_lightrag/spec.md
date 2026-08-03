# Spec: LightRAG Integration Pipeline — VietLegalGraphRAG

**Version**: 0.1-draft  
**Date**: 2026-07-31  
**Status**: Brainstorming → Approved for Experimentation  
**Scope**: `pipeline/06_lightrag/` — Experimental, offline, không production

---

## 1. Bối cảnh & Mục tiêu

### 1.1 Vấn đề hiện tại

Hệ thống VietLegalGraphRAG hiện dùng:
- **Elasticsearch** cho hybrid retrieval (dense + sparse/BM25)
- **Neo4j** cho knowledge graph với quan hệ pháp luật được định nghĩa thủ công (amendment, citation, replacement, v.v.)
- **LightRAG Service** (`lightrag_service.py`) là orchestrator — **không phải** thư viện LightRAG thực sự

Hạn chế:
- Graph Neo4j được xây dựng từ metadata cấu trúc — không khai thác nội dung văn bản để tự động phát hiện entity/relation
- Thiếu khả năng "graph-aware" query: trả lời câu hỏi phức tạp cần suy luận qua nhiều node
- Entity extraction hiện chưa có pipeline tự động

### 1.2 Mục tiêu thử nghiệm

1. **Xây dựng LightRAG index** từ corpus văn bản pháp luật Việt Nam — entity và relation được extract tự động bằng LLM
2. **Tận dụng GPU H100 droplet** với vLLM để:
   - LLM inference cho entity/relation extraction trong quá trình indexing
   - (Optional) LLM inference cho local querying
3. **Học từ LegalGraphRAG (ACL'26)**:
   - Legal ontology: hierarchy, amendment, citation, hiệu lực văn bản
   - Multi-agent legal reasoning approach
4. **Đánh giá chất lượng** so với pipeline ES + Neo4j hiện tại

### 1.3 Non-goals (giai đoạn này)

- Tích hợp vào Open WebUI pipe ngay
- Production deployment
- Thay thế hoàn toàn Elasticsearch/Neo4j
- Real-time indexing

---

## 2. Kiến trúc tổng quan

```
                         pipeline/06_lightrag/

  Corpus pháp luật VN ──► ingest.py
  (preprocessed JSON)         │
                               ▼
                      LightRAG Library (hkuds/lightrag)
                         │
                         ├── Entity/Rel Extraction ──► GPU H100 (vLLM)
                         │                              Qwen3-8B/14B
                         │                              (INDEXING LLM)
                         ├── Graph Store (NetworkX/local)
                         └── Vector Store (NanoVectorDB)
                               │
                               ▼
                         query.py
                         (modes: naive | local | global | hybrid)
                               │
                               └──► External LLM API (query/response)
                                     Groq/OpenAI/etc.
                               │
                               ▼
                         evaluate_lightrag.py
                         (compare vs ES + Neo4j baseline)
```

---

## 3. Component Design

### 3.1 LightRAG Library (hkuds/lightrag)

LightRAG hoạt động theo hai giai đoạn:

**Indexing (offline, dùng H100)**:
```
Document ─► Chunking ─► Entity Extraction (LLM) ─► Relation Extraction (LLM) ─► Graph Build ─► Vector Store
```

**Querying (online)**:
```
Query ─► Query Analysis ─► [naive|local|global|hybrid] ─► Graph Traversal + Vector Search ─► LLM Answer
```

Query modes của LightRAG:

| Mode | Mô tả | Phù hợp cho |
|------|--------|-------------|
| `naive` | RAG thông thường, không dùng graph | Baseline comparison |
| `local` | Tìm entity liên quan, traverse local neighborhood | Câu hỏi về entity cụ thể |
| `global` | Community detection, global context | Câu hỏi tổng quan, policy |
| `hybrid` | Kết hợp local + global | Câu hỏi phức tạp |
| `mix` | Kết hợp naive + hybrid | General purpose |

### 3.2 GPU Droplet (H100 + vLLM) — Indexing LLM

**Role**: Chỉ phục vụ quá trình **indexing** (entity/relation extraction)

**Recommended models** (theo thứ tự ưu tiên):
1. **Qwen3-8B** — multilingual, Vietnamese tốt, reasoning mode, nhẹ nhất cho H100
2. **Qwen3-14B** — cân bằng chất lượng/tốc độ
3. **Qwen2.5-72B-Instruct** — chất lượng cao nhất, cần quantization (AWQ/GPTQ)

**vLLM config example**:
```bash
# Trên H100 Droplet
vllm serve Qwen/Qwen3-8B \
  --api-key "your-vllm-key" \
  --port 8000 \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --enable-prefix-caching
```

**API config trong pipeline**:
```env
# LLM for indexing (H100 vLLM)
LIGHTRAG_LLM_BASE_URL=http://<H100_IP>:8000/v1
LIGHTRAG_LLM_API_KEY=your-vllm-key
LIGHTRAG_LLM_MODEL=Qwen/Qwen3-8B

# LLM for querying (external API)
LIGHTRAG_QUERY_LLM_BASE_URL=https://api.groq.com/openai/v1
LIGHTRAG_QUERY_LLM_API_KEY=your-groq-key
LIGHTRAG_QUERY_LLM_MODEL=llama-3.1-70b-versatile
```

### 3.3 Legal Ontology (từ LegalGraphRAG ACL'26)

Dựa trên insights từ `XMUDeepLIT/LegalGraphRAG`, ta xây dựng **legal-specific entity/relation types** để guide LLM extraction:

**Entity types**:
- `LEGAL_DOCUMENT` — Văn bản pháp luật (Luật, Nghị định, Thông tư, Quyết định...)
- `LEGAL_ARTICLE` — Điều khoản (Điều 5, Khoản 2...)
- `LEGAL_ORGANIZATION` — Cơ quan ban hành (Quốc hội, Chính phủ, Bộ...)
- `LEGAL_SUBJECT` — Chủ thể pháp luật (công dân, doanh nghiệp...)
- `LEGAL_CONCEPT` — Khái niệm pháp lý (quyền sở hữu, trách nhiệm hình sự...)
- `LEGAL_PENALTY` — Hình phạt, chế tài
- `LEGAL_PROCEDURE` — Thủ tục hành chính, quy trình pháp lý
- `TEMPORAL` — Ngày hiệu lực, thời hạn, giai đoạn

**Relation types**:
- `AMENDS` — Sửa đổi, bổ sung
- `REPLACES` — Thay thế, bãi bỏ
- `REFERENCES` — Dẫn chiếu
- `IMPLEMENTS` — Hướng dẫn thi hành
- `GOVERNS` — Điều chỉnh chủ thể/lĩnh vực
- `HAS_ARTICLE` — Văn bản có điều khoản
- `REQUIRES` — Điều kiện bắt buộc
- `PENALIZES` — Áp dụng chế tài
- `EFFECTIVE_FROM` — Hiệu lực từ ngày
- `ISSUED_BY` — Ban hành bởi

### 3.4 Embedding Strategy

| Option | Ưu điểm | Nhược điểm |
|--------|---------|------------|
| `darklethelong/vnlegal-lal` | Cùng model với corpus hiện tại | Cần GPU/ONNX setup |
| `bge-m3` qua Ollama | LegalGraphRAG dùng, hỗ trợ Vietnamese | Cần chạy Ollama local |
| OpenAI `text-embedding-3-small` | Dễ dùng nhất | Có chi phí API |

**Recommendation**: Dùng `bge-m3` cho thử nghiệm (giống LegalGraphRAG), dài hạn migrate về `vnlegal-lal`.

### 3.5 Storage Strategy (thử nghiệm)

| Store | Backend |
|-------|---------|
| KV Store (chunks, entities) | JSON files (local) — `JsonKVStorage` |
| Vector Store | NanoVectorDB (built-in) — `NanoVectorDBStorage` |
| Graph Store | NetworkX (in-memory) — `NetworkXStorage` |

> **Future**: LightRAG hỗ trợ Neo4j trực tiếp (`Neo4JStorage`) — có thể tái dụng Neo4j hiện có.

---

## 4. Data Flow chi tiết

### 4.1 Indexing Flow

```
Input: data/preprocessed/*.json (các chunk văn bản pháp luật)

Step 1 - Document Loading:
  ingest.py đọc corpus → convert thành List[str] documents

Step 2 - LightRAG Insertion (lightrag.insert):
  ├── Chunking (configurable chunk_size/overlap)
  ├── Entity Extraction → gọi vLLM H100 endpoint
  │     Prompt: legal_entity_extraction_prompt (tiếng Việt)
  │     Extract: (entity_name, entity_type, entity_description)
  ├── Relation Extraction → gọi vLLM H100 endpoint
  │     Extract: (src_entity, rel_type, tgt_entity, description, weight)
  ├── Community Detection (Leiden algorithm)
  ├── Community Summary → gọi vLLM H100 endpoint
  └── Store: KV + Graph + Vector stores

Output: ./lightrag_index/
  ├── kv_store_full_docs.json
  ├── kv_store_text_chunks.json
  ├── kv_store_llm_response_cache.json
  ├── graph_chunk_entity_relation.graphml
  └── vdb_entities.json, vdb_chunks.json, vdb_relationships.json
```

### 4.2 Query Flow

```
Input: User query (string)

Step 1 - lightrag.query(query, param=QueryParam(mode="hybrid"))
  ├── [naive]  Vector search only → top-k chunks
  ├── [local]  Entity linking → graph neighborhood → context assembly
  ├── [global] Community lookup → global context → LLM summary
  └── [hybrid] local + global combined

Step 2 - Answer Generation:
  → External LLM generates final answer

Output: answer (string) + tracing info
```

---

## 5. Legal-specific Customizations (từ LegalGraphRAG)

### 5.1 Custom Extraction Prompt (tiếng Việt)

```python
LEGAL_ENTITY_EXTRACTION_PROMPT = """
Bạn là chuyên gia pháp luật Việt Nam. Hãy phân tích đoạn văn bản pháp luật sau
và trích xuất TẤT CẢ các thực thể pháp lý quan trọng.

Loại thực thể: LEGAL_DOCUMENT, LEGAL_ARTICLE, LEGAL_ORGANIZATION,
LEGAL_SUBJECT, LEGAL_CONCEPT, LEGAL_PROCEDURE, LEGAL_PENALTY

Văn bản: {input_text}

Định dạng JSON:
[{"entity_name": "...", "entity_type": "...", "description": "..."}]
"""
```

### 5.2 Version Chain Awareness

LegalGraphRAG chú trọng vào **hiệu lực văn bản** (amendment chains). Ta sẽ:
1. Detect các relation `AMENDS`, `REPLACES` trong graph extraction
2. Tag entities với `effective_from`, `effective_until`
3. Khi query, filter/warn về văn bản hết hiệu lực

### 5.3 Multi-agent Legal Reasoning (Phase 2)

Học từ LegalGraphRAG multi-agent approach:
- **Retrieval Agent**: Tìm kiếm entity/relation liên quan
- **Reasoning Agent**: Suy luận qua graph
- **Citation Agent**: Trích dẫn và format kết quả

---

## 6. Evaluation Strategy

### 6.1 Metrics

| Metric | Mô tả |
|--------|-------|
| Retrieval Quality | Recall@k, Precision@k, MRR |
| Answer Quality | ROUGE-L, BERTScore, faithfulness |
| Graph Coverage | Entity coverage, relation completeness |
| Latency | Indexing time, query latency |

### 6.2 Comparison Baselines

| System | Config |
|--------|--------|
| Baseline A | ES keyword-only (sparse) |
| Baseline B | ES hybrid (sparse + dense) |
| Baseline C | ES hybrid + Neo4j graph |
| LightRAG naive | LightRAG, mode=naive |
| LightRAG hybrid | LightRAG, mode=hybrid |

---

## 7. Configuration Reference

```env
# ============================================================
# LightRAG Pipeline Configuration — .env.lightrag
# ============================================================

# Indexing LLM (GPU H100 + vLLM)
LIGHTRAG_LLM_BASE_URL=http://YOUR_H100_IP:8000/v1
LIGHTRAG_LLM_API_KEY=your-vllm-api-key
LIGHTRAG_LLM_MODEL=Qwen/Qwen3-8B
LIGHTRAG_LLM_MAX_TOKENS=32768
LIGHTRAG_LLM_TEMPERATURE=0.0

# Query LLM (External API)
LIGHTRAG_QUERY_LLM_BASE_URL=https://api.openai.com/v1
LIGHTRAG_QUERY_LLM_API_KEY=your-openai-key
LIGHTRAG_QUERY_LLM_MODEL=gpt-4o-mini

# Embedding
LIGHTRAG_EMBEDDING_MODEL=BAAI/bge-m3
LIGHTRAG_EMBEDDING_PROVIDER=hf_local   # or openai_compatible

# LightRAG Storage
LIGHTRAG_WORKING_DIR=./lightrag_index
LIGHTRAG_GRAPH_STORAGE=NetworkXStorage
LIGHTRAG_KV_STORAGE=JsonKVStorage
LIGHTRAG_VECTOR_STORAGE=NanoVectorDBStorage

# Indexing Params
LIGHTRAG_CHUNK_TOKEN_SIZE=1200
LIGHTRAG_CHUNK_OVERLAP_TOKEN_SIZE=100
LIGHTRAG_ENTITY_EXTRACT_MAX_GLEANING=1
LIGHTRAG_ENABLE_LLM_CACHE=true

# Input Corpus
LIGHTRAG_CORPUS_DIR=../../data/preprocessed
LIGHTRAG_CORPUS_GLOB=*.json
LIGHTRAG_MAX_DOCS=500   # giới hạn cho thử nghiệm

# Query Params
LIGHTRAG_QUERY_MODE=hybrid
LIGHTRAG_QUERY_TOP_K=10
```

---

## 8. Dependencies

```
lightrag-hku>=1.3.0
openai>=1.0.0
python-dotenv>=1.0.0
networkx>=3.0
nano-vectordb>=0.0.3
tiktoken>=0.7.0
tenacity>=8.2.0
rich>=13.0.0
pandas>=2.0.0
tqdm>=4.66.0
sentence-transformers>=2.7.0   # for local bge-m3 embedding
```

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| vLLM H100 không accessible | Medium | High | Fallback sang OpenAI API |
| Entity extraction kém cho tiếng Việt | Medium | High | Custom legal prompt + few-shot |
| Indexing quá chậm/tốn | Low | Medium | Giới hạn MAX_DOCS, enable cache |
| LightRAG version incompatibility | Low | Medium | Pin version, test nhỏ trước |
| Graph quality vs Neo4j hiện tại | Unknown | High | Evaluation suite đo định lượng |

---

## 10. Tham chiếu

- [LightRAG GitHub](https://github.com/HKUDS/LightRAG)
- [LegalGraphRAG ACL'26](https://github.com/XMUDeepLIT/LegalGraphRAG)
- [vLLM Docs](https://docs.vllm.ai)
- [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B)
- [bge-m3](https://huggingface.co/BAAI/bge-m3)
- Current developer guide: [`docs/developer_guide.md`](../../docs/developer_guide.md)
