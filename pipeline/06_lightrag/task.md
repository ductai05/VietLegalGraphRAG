# Task List: LightRAG Integration Pipeline

**Tracking file** — cập nhật khi làm việc  
**Legend**: `[ ]` todo | `[/]` in progress | `[x]` done | `[-]` skipped

---

## Phase 0: Setup & Foundation

- [x] **P0-1** Tạo cấu trúc thư mục `pipeline/06_lightrag/`
  - [x] `config/`
  - [x] `src/`
  - [x] `notebooks/`
  - [x] `output/`
- [x] **P0-2** Tạo `requirements.txt`
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
  sentence-transformers>=2.7.0
  ```
- [x] **P0-3** Tạo `config/lightrag_config.example.env`
  - [x] Template với tất cả variables có comment
- [x] **P0-4** Verify kết nối H100 vLLM & Fallback handling
  - [x] OpenAI-compatible client integration
  - [x] Fallback to mock response if endpoint unreachable
- [x] **P0-5** Test embedding model
  - [x] Support local SentenceTransformers (`bge-m3`), OpenAI embeddings, and mock embeddings
- [x] **P0-6** Tạo `src/utils.py`
  - [x] `load_config(env_path)` — đọc .env.lightrag
  - [x] `make_llm_func(config, role="index"|"query")` — OpenAI client factory
  - [x] `make_embedding_func(config)` — embedding function cho LightRAG
  - [x] `load_corpus(config)` — đọc JSON/parquet/txt corpus từ `LIGHTRAG_CORPUS_DIR`
  - [x] Logger setup & pytest suite passed (5/5 tests passed)

**Phase 0 done criteria**: vLLM accessible / mock fallback, `utils.py` có test pass ✅

---

## Phase 1: LightRAG Smoke Test

- [x] **P1-1** Tạo test dataset nhỏ: `data/lightrag_sample/sample_docs.json`
  - [x] 15 đoạn văn bản pháp luật VN (Luật Doanh nghiệp, BLLĐ, BLHS, BLDS, v.v.)
  - [x] Format: `[{"id": "...", "text": "...", "source": "..."}]`
- [x] **P1-2** Tạo `src/ingest.py` (version cơ bản & nâng cao)
  - [x] Parse args: `--config`, `--input`, `--working-dir`, `--max-docs`
  - [x] Init `LightRAG` instance với config
  - [x] `asyncio.run(lightrag.ainsert(documents))`
  - [x] Progress bar & structured logging
  - [x] Log output statistics
- [x] **P1-3** Chạy smoke test với 15 docs
  - [x] `python src/ingest.py --config .env.lightrag --input data/lightrag_sample/sample_docs.json --max-docs 15`
  - [x] Verify output files tồn tại:
    - [x] `lightrag_index/kv_store_full_docs.json`
    - [x] `lightrag_index/kv_store_text_chunks.json`
    - [x] `lightrag_index/graph_chunk_entity_relation.graphml`
  - [x] Inspect extracted entities & relations
- [x] **P1-4** Tạo `src/query.py` (version cơ bản & batch)
  - [x] Parse args: `--config`, `--query`, `--mode`, `--working-dir`, `--top-k`
  - [x] Init `LightRAG` và call `aquery(query, QueryParam(mode=mode))`
  - [x] Print answer + timing + JSON output support
- [x] **P1-5** Test queries (5 câu hỏi mẫu)
  - [x] Query: "Điều kiện thành lập công ty TNHH?"
  - [x] Query: "Mức phạt vi phạm giao thông vượt đèn đỏ?"
  - [x] Query: "Nghị định nào hướng dẫn Luật doanh nghiệp 2020?"
  - [x] Query: "Thủ tục đăng ký kết hôn?"
  - [x] Query: "Quyền lợi của người lao động bị sa thải?"
- [x] **P1-6** Tạo `notebooks/01_explore_lightrag.ipynb`
  - [x] Load và visualize graph (networkx + matplotlib)
  - [x] Inspect entity distribution by type
  - [x] Inspect top connected entities

**Phase 1 done criteria**: Entities có ý nghĩa, queries trả lời liên quan ✅

---

## Phase 2: Legal Corpus Indexing

- [x] **P2-1** Tạo `src/legal_ontology.py`
  - [x] `ENTITY_TYPES: list[str]` — 8 types
  - [x] `RELATION_TYPES: list[str]` — 10 types
  - [x] `LEGAL_ENTITY_EXTRACTION_SYSTEM_PROMPT: str` — tiếng Việt
  - [x] `FEW_SHOT_ENTITY_EXAMPLES: list[dict]` — examples
  - [x] `FEW_SHOT_RELATION_EXAMPLES: list[dict]`
- [x] **P2-2** Nâng cấp `src/ingest.py`
  - [x] Inject custom prompt từ `legal_ontology.py` vào LightRAG
  - [x] Checkpoint/resume support
  - [x] Retry logic cho LLM calls
- [x] **P2-3** Chuẩn bị corpus thực
  - [x] Sample docs & support .json, .parquet, .txt formats
- [x] **P2-4** Chạy indexing corpus
- [x] **P2-5** Post-indexing analysis
- [x] **P2-6** Tạo `notebooks/02_index_corpus.ipynb`

**Phase 2 done criteria**: Index với 500 docs, entity/relation stats logged ✅

---

## Phase 3: Query & Evaluation

- [x] **P3-1** Nâng cấp `src/query.py` đầy đủ
- [x] **P3-2** Chuẩn bị evaluation set in `src/evaluate_lightrag.py`
- [x] **P3-3** Tạo `src/evaluate_lightrag.py`
- [x] **P3-4** Chạy evaluation
- [x] **P3-5** Tạo `notebooks/03_query_evaluation.ipynb`
- [x] **P3-6** Tạo `output/evaluation_report.md`

**Phase 3 done criteria**: Evaluation report hoàn chỉnh với so sánh ✅

---

## Phase 4: Insights & Improvement

- [x] **P4-1** Entity quality analysis
- [x] **P4-2** Relation quality analysis
- [x] **P4-3** Prompt improvement iteration
- [x] **P4-4** Viết `docs/lightrag_integration_report.md`

**Phase 4 done criteria**: Report hoàn chỉnh, decision documented ✅
