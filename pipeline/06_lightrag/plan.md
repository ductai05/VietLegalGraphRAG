# Plan: LightRAG Integration Pipeline — VietLegalGraphRAG

**Version**: 0.1  
**Date**: 2026-07-31  
**Owner**: VietLegalGraphRAG Team  
**Scope**: `pipeline/06_lightrag/` — Experimental

---

## Tổng quan phases

```
Phase 0 ─── Setup & Foundation            (~0.5 ngày)
Phase 1 ─── LightRAG Smoke Test           (~1 ngày)
Phase 2 ─── Legal Corpus Indexing         (~2-3 ngày)
Phase 3 ─── Query & Evaluation            (~2 ngày)
Phase 4 ─── Insights & Improvement        (~ongoing)
```

---

## Phase 0: Setup & Foundation

**Mục tiêu**: Cài đặt môi trường, kiểm tra kết nối H100 droplet, tạo cấu trúc thư mục

### Tasks

- [ ] Tạo cấu trúc thư mục `pipeline/06_lightrag/`
  - `config/`, `src/`, `notebooks/`, `output/`
- [ ] Tạo `requirements.txt` với `lightrag-hku` và dependencies
- [ ] Tạo `config/lightrag_config.example.env` với tất cả biến cần thiết
- [ ] Verify kết nối H100 droplet: ping vLLM endpoint `/health`
- [ ] Test LLM inference: gọi `chat/completions` với câu đơn giản tiếng Việt
- [ ] Setup embedding: test `bge-m3` local hoặc qua vLLM
- [ ] Tạo `src/utils.py`: config loader, LLM client factory, embedding client factory

**Deliverable**: Pipeline skeleton + connectivity confirmed

---

## Phase 1: LightRAG Smoke Test

**Mục tiêu**: Xác minh LightRAG library hoạt động đúng với 10-20 documents nhỏ

### Tasks

- [ ] Tạo `src/ingest.py`: script ingestion cơ bản
  - Đọc corpus JSON
  - Init `LightRAG` instance với config
  - Gọi `lightrag.insert(documents)`
  - Progress logging
- [ ] Tạo test dataset nhỏ: 10-20 đoạn văn bản pháp luật VN mẫu
- [ ] Chạy indexing smoke test với 10 docs
  - Kiểm tra entity extraction output (tiếng Việt)
  - Kiểm tra graph được tạo (`graph_chunk_entity_relation.graphml`)
  - Kiểm tra vector store được tạo
- [ ] Tạo `src/query.py`: script query cơ bản
  - Query theo 4 modes: naive, local, global, hybrid
  - Format và print output
- [ ] Test query với 5-10 câu hỏi pháp luật đơn giản
- [ ] Notebook `notebooks/01_explore_lightrag.ipynb`
  - Visualize graph (NetworkX + matplotlib)
  - Inspect extracted entities/relations

**Deliverable**: Confirmed LightRAG works end-to-end với tiếng Việt

**Go/No-go criteria**:
- Entities được extract có ý nghĩa (legal entities, không phải garbage)
- Queries trả lời có liên quan đến câu hỏi pháp luật
- Không có critical errors

---

## Phase 2: Legal Corpus Indexing

**Mục tiêu**: Build LightRAG index từ corpus pháp luật VN thực sự (up to 500 docs)

### Tasks

- [ ] Tạo `src/legal_ontology.py`
  - Define entity_types list
  - Define relation_types list
  - Custom extraction prompt (tiếng Việt, legal domain)
  - Few-shot examples từ LegalGraphRAG approach
- [ ] Cải thiện `src/ingest.py`
  - Inject custom entity/relation types vào LightRAG config
  - Inject custom extraction prompt
  - Batch processing với retry/resume support
  - Progress checkpoint (resume từ điểm dừng)
  - LLM cache enable
- [ ] Chuẩn bị corpus thực:
  - Lấy từ `data/preprocessed/` (corpus pháp luật VN hiện có)
  - Giới hạn `MAX_DOCS=500` cho thử nghiệm đầu tiên
  - Format: convert từ chunked JSON sang plain text nếu cần
- [ ] Chạy indexing trên 500 docs
  - Monitor vLLM H100 utilization
  - Log entity/relation statistics
  - Estimate total indexing cost/time
- [ ] Notebook `notebooks/02_index_corpus.ipynb`
  - Statistics: số entities, số relations, distribution theo type
  - Graph visualization (sample subgraph)
  - Entity coverage analysis

**Deliverable**: LightRAG index với 500 docs pháp luật VN, entity/relation graph

**Expected metrics**:
- Số entities: ~5,000-20,000 (ước tính 10-40 entities/doc)
- Số relations: ~10,000-50,000
- Indexing time: ~2-6 giờ với Qwen3-8B trên H100 (100 tokens/s)

---

## Phase 3: Query & Evaluation

**Mục tiêu**: Đánh giá chất lượng LightRAG so với pipeline hiện tại

### Tasks

- [ ] Tạo `src/evaluate_lightrag.py`
  - Dùng evaluation set từ `pipeline/05_evaluation/`
  - Compare 5 baselines: ES-sparse, ES-hybrid, ES+Neo4j, LightRAG-naive, LightRAG-hybrid
  - Metrics: ROUGE-L, BERTScore, retrieval precision, latency
- [ ] Chạy evaluation trên test set (dùng `generate_eval_questions.py` nếu chưa có gold set)
- [ ] Tạo `src/query.py` đầy đủ:
  - CLI interface: `--query`, `--mode`, `--top-k`, `--output-format`
  - Output: answer + sources + graph path (multi-hop)
  - Latency measurement
- [ ] Notebook `notebooks/03_query_evaluation.ipynb`
  - Side-by-side comparison: ES+Neo4j vs LightRAG
  - Qualitative analysis: câu hỏi nào LightRAG tốt hơn/kém hơn
  - Error analysis
- [ ] Tạo `output/evaluation_report.md` với kết quả

**Deliverable**: Evaluation report với so sánh định lượng và định tính

---

## Phase 4: Insights & Improvement

**Mục tiêu**: Tổng hợp learnings, đề xuất hướng cải thiện

### Tasks

- [ ] Phân tích entity quality:
  - Entities nào được extract tốt? (LEGAL_DOCUMENT, LEGAL_ARTICLE)
  - Entities nào extract kém? (LEGAL_SUBJECT, TEMPORAL)
- [ ] Phân tích relation quality:
  - Relations `AMENDS`, `REPLACES` có chính xác không?
  - So sánh với Neo4j relations thủ công
- [ ] Đề xuất cải tiến:
  - Prompt engineering cho legal domain
  - Hybrid approach: dùng LightRAG graph + ES retrieval
  - Tích hợp metadata-based relations từ Neo4j vào LightRAG graph
- [ ] Viết `docs/lightrag_integration_report.md`
  - Tóm tắt findings
  - Quyết định: nên tích hợp LightRAG vào production không?
  - Roadmap nếu tích hợp

**Deliverable**: Report + Go/No-go decision cho production integration

---

## Milestones & Timeline

| Milestone | Phase | Estimated Duration |
|-----------|-------|-------------------|
| M0: Environment ready | Phase 0 | 0.5 ngày |
| M1: Smoke test passed | Phase 1 | +1 ngày |
| M2: Full corpus indexed | Phase 2 | +3 ngày |
| M3: Evaluation complete | Phase 3 | +2 ngày |
| M4: Decision & report | Phase 4 | +1 ngày |
| **Total** | | **~8 ngày** |

---

## Dependencies & Prerequisites

| Dependency | Status | Action nếu chưa có |
|------------|--------|-------------------|
| GPU H100 Droplet với vLLM | Cần verify | Setup vLLM server |
| Corpus pháp luật VN (preprocessed) | Có trong `data/` | — |
| `lightrag-hku` library | Cần cài | `pip install lightrag-hku` |
| `bge-m3` model weights | Cần download | `huggingface-cli download BAAI/bge-m3` |
| Evaluation set từ pipeline/05 | Có | Dùng lại |
| External LLM API key (query) | Cần | Groq/OpenAI key |

---

## Rủi ro và contingency

| Rủi ro | Contingency |
|--------|-------------|
| H100 vLLM không accessible | Dùng OpenAI API cho indexing (tốn chi phí hơn) |
| LightRAG extract entity kém | Tăng few-shot examples, thử model lớn hơn |
| Indexing quá chậm | Giảm MAX_DOCS xuống 100, tối ưu batch size |
| Kết quả evaluation không tốt | Vẫn có learnings — document lại và đề xuất alternatives |
