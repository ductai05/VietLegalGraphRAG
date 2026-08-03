# Decision Log: LightRAG Integration Pipeline

**Format**: Decision | Alternatives Considered | Rationale  
**Date started**: 2026-07-31

---

## D1 — Dùng thư viện `hkuds/lightrag` làm GraphRAG framework

**Decided**: Sử dụng `lightrag-hku` pip package làm orchestration layer cho graph-based RAG

**Alternatives considered**:
- A. Tự xây dựng graph RAG từ đầu (entity extraction + graph + retrieval)
- B. Dùng Microsoft GraphRAG
- C. Nâng cấp LightRAG Service hiện tại (`lightrag_service.py`) thêm tính năng

**Rationale**:
- LightRAG có sẵn pipeline hoàn chỉnh (chunk → extract → graph → query), tiết kiệm thời gian
- LegalGraphRAG (ACL'26) đề cập LightRAG là một baseline — có thể so sánh trực tiếp
- Microsoft GraphRAG phức tạp hơn và ít flexible hơn cho customization
- Option C không giải quyết được vấn đề entity extraction tự động

---

## D2 — GPU H100 + vLLM chỉ phục vụ INDEXING, không phải querying

**Decided**: H100 droplet phục vụ entity/relation extraction (indexing LLM). Query/response dùng external LLM API.

**Alternatives considered**:
- A. H100 phục vụ cả indexing lẫn querying
- B. H100 chỉ phục vụ querying, indexing dùng external API

**Rationale**:
- Indexing là tác vụ batch, có thể chạy offline, tốn nhiều compute — H100 phù hợp nhất
- Querying cần latency thấp và reliability cao — external API (OpenAI/Groq) phù hợp hơn
- H100 có thể bận khi user query, gây conflict nếu dùng cho cả hai
- Phân tách rõ ràng giúp dễ scale và monitor

---

## D3 — Scope: `pipeline/06_lightrag/` experimental, không tích hợp production ngay

**Decided**: Tạo thư mục pipeline riêng biệt để thử nghiệm, không deploy lên production trong giai đoạn này

**Alternatives considered**:
- A. Tích hợp trực tiếp vào `src/vietlegal_rag/services/`
- B. Branch riêng trên git để thử nghiệm

**Rationale**:
- Cần validate chất lượng trước khi đưa vào production
- Thư mục pipeline riêng dễ review, không ảnh hưởng hệ thống đang chạy
- Pattern nhất quán với các pipeline khác (`01_eda`, `02_preprocessing`, v.v.)
- Dễ cleanup nếu kết quả không tốt

---

## D4 — Storage: NetworkX (in-memory) cho giai đoạn thử nghiệm

**Decided**: Dùng `NetworkXStorage` cho graph store và `JsonKVStorage` cho KV store

**Alternatives considered**:
- A. Dùng Neo4j ngay (tái dụng instance hiện có)
- B. Dùng AGE (Apache Graph Extension cho PostgreSQL)
- C. Dùng TigerGraph hoặc ArangoDB

**Rationale**:
- NetworkX đơn giản nhất, không cần setup infrastructure
- Cho thử nghiệm với 500 docs, NetworkX đủ dùng (in-memory fit)
- Neo4j có thể migrate sau nếu quyết định đưa lên production (LightRAG hỗ trợ `Neo4JStorage`)
- Giữ đúng nguyên tắc: đơn giản hóa trong giai đoạn thử nghiệm

---

## D5 — Embedding: `bge-m3` cho thử nghiệm ban đầu

**Decided**: Dùng `BAAI/bge-m3` làm embedding model cho LightRAG vector store

**Alternatives considered**:
- A. `darklethelong/vnlegal-lal` — model hiện tại của hệ thống
- B. OpenAI `text-embedding-3-small`
- C. `multilingual-e5-large`

**Rationale**:
- `bge-m3` được dùng trong LegalGraphRAG (ACL'26) — cho phép so sánh tương đồng
- Hỗ trợ tiếng Việt tốt, multilingual, có thể chạy local
- `vnlegal-lal` tốt hơn cho domain Vietnamese legal nhưng cần benchmark trước
- OpenAI embedding có cost và dependency ngoài

**Note**: Long-term, nên benchmark `bge-m3` vs `vnlegal-lal` cho LightRAG vector store

---

## D6 — Legal Ontology: Custom entity/relation types (không dùng LightRAG default)

**Decided**: Override default entity/relation types của LightRAG với legal-specific types tiếng Việt

**Alternatives considered**:
- A. Dùng default LightRAG types (person, organization, location, event, concept)
- B. Dùng types từ LegalGraphRAG ACL'26 trực tiếp (designed for Chinese law)

**Rationale**:
- Default types không phù hợp cho pháp luật VN (thiếu LEGAL_DOCUMENT, LEGAL_ARTICLE, v.v.)
- LegalGraphRAG types designed for Chinese — cần adapt cho hệ thống pháp luật VN
- Custom types cho phép capture legal hierarchy VN: Luật > Nghị định > Thông tư > Quyết định
- Tiếng Việt cần prompt tiếng Việt để extract chính xác hơn

---

## D7 — Mô hình LLM trên H100: để linh hoạt, recommend Qwen3-8B

**Decided**: Không hard-code model — configurable qua env. Recommend Qwen3-8B làm default.

**Alternatives considered**:
- A. Hard-code Qwen3-8B
- B. Qwen2.5-72B (cần quantization)
- C. DeepSeek-R1
- D. Llama-3.3-70B

**Rationale**:
- Qwen3-8B: nhẹ nhất, Vietnamese tốt, reasoning mode (`/think`), fit H100 80GB dễ dàng
- Có thể upgrade Qwen3-14B hoặc 72B nếu chất lượng entity extraction chưa đủ
- Giữ flexible vì team chưa quyết định chính thức
- LegalGraphRAG dùng Qwen3-8B — dễ reproduce và compare

---

## D8 — Scope evaluation: so sánh 5 baselines

**Decided**: Evaluation framework compare: ES-sparse, ES-hybrid, ES+Neo4j, LightRAG-naive, LightRAG-hybrid

**Rationale**:
- Cần baseline nhiều tầng để hiểu rõ contribution của từng component
- Reuse code từ `pipeline/05_evaluation/` để đảm bảo consistency
- 5 baselines đủ để ra quyết định production, không over-engineer
