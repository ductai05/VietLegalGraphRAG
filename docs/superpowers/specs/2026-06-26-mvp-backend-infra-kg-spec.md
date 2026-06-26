# MVP Backend, Infrastructure, and Knowledge Graph Spec

## 1. Scope

MVP này phục vụ demo cho một giảng viên, không phải triển khai production. Mục tiêu là có một hệ thống tra cứu pháp luật chạy ổn định, có trích dẫn, có lựa chọn chế độ truy xuất, và có minh họa Knowledge Graph đủ thuyết phục.

Trọng tâm công việc:

- Backend API cho truy vấn pháp luật.
- Elasticsearch cho cả dense retrieval và sparse retrieval.
- Sáu cấu hình retrieval: `dense`, `dense_rerank`, `sparse`, `sparse_rerank`, `hybrid`, `hybrid_rerank`.
- Hybrid retrieval bằng RRF, có tùy chọn rerank cho cả dense, sparse và hybrid.
- Neo4j cho quan hệ văn bản pháp luật và truy vấn graph.
- LightRAG làm lớp orchestration GraphRAG trên Neo4j và Elasticsearch.
- Tài liệu API để thành viên Frontend đọc và tích hợp.
- Evaluation để chứng minh chất lượng retrieval và KG.
- Hạ tầng demo đơn giản, ưu tiên Docker Compose hoặc một server nhỏ.

Không thuộc MVP:

- Stress test 100 request/s.
- Prometheus, Grafana đầy đủ.
- CI/CD build, push registry, deploy production tự động.
- Incremental update không dừng hệ thống.
- Multi-tenant auth, phân quyền người dùng.
- Tối ưu chi phí cloud ở mức production. MVP chỉ cần lựa chọn deploy đủ chạy demo.

## 2. Current State Assessment

Repo đã có nhiều nền tảng sử dụng được:

- `pipeline/04_embedding` đã hỗ trợ dense retrieval trên Elasticsearch.
- `pipeline/05_sparse_retrieval` đã hỗ trợ BM25 trên Elasticsearch.
- `pipeline/07_evaluation/hybrid_search.py` đã có hybrid retrieval bằng RRF và rerank.
- `pipeline/05_graph` đã có graph builder, schema, CSV export, Cypher import và audit script.
- `output/kg_progress/kg_progress_report.md` ghi nhận lần audit trước có khoảng 353k Document, 7.47M Article, 122k Document-Document relationships.

Các vấn đề cần chỉnh trước khi đưa KG vào app:

- Artifact Neo4j import từng được audit tại `data/processed/neo4j_imports`, nhưng thư mục này hiện không có trong workspace. MVP phải tái sinh artifacts từ pipeline.
- Code KG hiện chưa loại self-loop. Kiểm tra nhanh với `doc_id == other_doc_id` vẫn tạo cạnh `CITES`.
- Code KG hiện chưa đảo chiều các quan hệ bị động như `IS_AMENDED_BY`, dù tài liệu nói sẽ đảo chiều.
- Code hiện giữ nhiều loại edge như `CITES_AS_BASIS`, `GUIDES_DETAIL`, `SUPPLEMENTS`, `SUSPENDS`, `RELATED_TO`, trong khi spec MVP yêu cầu 4 loại chính: `AMENDS`, `CITES`, `REPEALS`, `GUIDELINES`.
- `chunk_node_id()` luôn thêm prefix `chunk:`, nên nếu input `chunk_id` đã là `chunk:1:000001` thì node id thành `chunk:chunk:1:000001`. Cần chuẩn hóa lại để tránh double-prefix.
- Neo4j import hiện lưu nhiều thuộc tính trong `properties_json`, tiện để import nhưng không tốt cho query/filter. MVP nên tách các field hay dùng thành property typed trực tiếp: `doc_id`, `document_number`, `title`, `legal_type`, `effect_status`, `issuance_date`, `effect_date`, `chunk_id`, `text`.
- Audit trước cho thấy 10 retrieval miss đều map được vào KG, nhưng direct Document-Document bridge là 0/10. KG hiện hữu tốt cho provenance và legal relation query, chưa chứng minh được hiệu quả mạnh trong retrieval expansion.
- Import report có 142 duplicate metadata warnings ở Authority/Sector. Không phá hỏng demo, nhưng nên deduplicate trước import để giảm warning.

Kết luận kỹ thuật về KG hiện tại:

- Không cần thiết kế lại từ đầu. Mô hình Document, Article, Document-Document relation và HAS_ARTICLE vẫn đúng hướng cho GraphRAG pháp luật.
- Cần rebuild trước khi đưa vào ứng dụng. Lý do là graph hiện tại chưa đạt invariant quan trọng của MVP: không self-loop, hướng quan hệ thống nhất, 4 nhãn quan hệ chính, Article id không double-prefix, và typed properties cho Neo4j query.
- Nên xem lần build hiện tại là prototype artifact, không phải KG production của demo.

## 3. Target Architecture

```text
Frontend
  |
  | HTTP JSON
  v
FastAPI Backend
  |
  |-- RetrievalService
  |     |-- Dense Elasticsearch index
  |     |-- Sparse Elasticsearch index
  |     |-- Hybrid RRF
  |     `-- Optional reranker
  |
  |-- GraphRetriever
  |     `-- Neo4j
  |
  |-- LightRAGService
  |     |-- GraphRetriever
  |     |-- RetrievalService
  |     `-- AnswerService
  |
  |-- AnswerService
  |     `-- LLM provider
  |
  `-- Evaluation and health endpoints
```

Backend trả về cả answer, citations, retrieval traces và graph evidence. FE chỉ cần render các field này, không cần biết chi tiết Elasticsearch hoặc Neo4j.

## 4. Retrieval Modes

FE có hai nhóm cấu hình:

- `retrieval_mode`: một trong `dense`, `sparse`, `hybrid`.
- `rerank.enabled`: `true` hoặc `false`.

Backend quy đổi thành 6 cấu hình thực thi:

| `retrieval_mode` | `rerank.enabled` | Execution mode | Ý nghĩa |
| --- | --- | --- | --- |
| `dense` | `false` | `dense` | Chỉ dùng vector search trên Elasticsearch dense index |
| `dense` | `true` | `dense_rerank` | Dense candidates, sau đó rerank bằng cross-encoder |
| `sparse` | `false` | `sparse` | Chỉ dùng BM25 trên Elasticsearch sparse index |
| `sparse` | `true` | `sparse_rerank` | Sparse candidates, sau đó rerank bằng cross-encoder |
| `hybrid` | `false` | `hybrid` | Chạy dense và sparse song song, trộn bằng RRF |
| `hybrid` | `true` | `hybrid_rerank` | Hybrid RRF candidates, sau đó rerank bằng cross-encoder |

Rerank config:

- `enabled`: bật hoặc tắt rerank.
- `model`: ví dụ `BAAI/bge-reranker-v2-m3`.
- `candidate_k`: số candidates đưa vào reranker, mặc định `50`.
- `batch_size`: mặc định `8`.
- `device`: `cpu`, `cuda`, hoặc `auto`.
- `timeout_ms`: timeout riêng cho reranker, mặc định `30000`.

LLM answer config:

- `temperature`: điều chỉnh độ quyết đoán hoặc sáng tạo của câu trả lời.
- Mặc định MVP: `0.2` cho trả lời pháp luật vì ưu tiên ổn định và bám nguồn.
- Cho phép FE chỉnh trong khoảng `0.0` đến `1.0`.
- Không dùng temperature để thay đổi retrieval quality. Retrieval quality phụ thuộc mode, filter, rerank và graph expansion.

Các filter bắt buộc hỗ trợ:

- `effect_status`: ví dụ `Còn hiệu lực`.
- `legal_type`: ví dụ `Luật`, `Nghị định`, `Thông tư`.
- `legal_sectors` hoặc `linh_vuc`.
- `issuing_authority`.
- `issuance_date` range nếu index đã có field chuẩn hóa.

Mặc định của demo:

- `retrieval_mode = hybrid`.
- `rerank.enabled = true`.
- `top_k = 5`.
- `candidate_k = 50`.
- `require_effective = true` nếu người dùng bật lọc văn bản còn hiệu lực.

## 5. Knowledge Graph MVP Schema

### Nodes

`Document`

- `id`: dạng `doc:<doc_id>`.
- `doc_id`.
- `document_number`.
- `title`.
- `legal_type`.
- `effect_status`.
- `issuing_authority`.
- `issuance_date`.
- `effect_date`.
- `effectless_date`.
- `legal_sectors`.

`Article`

- `id`: ưu tiên giữ đúng `chunk_id`, không double-prefix.
- `chunk_id`.
- `doc_id`.
- `text`.
- `chunk_type`.
- `section_path`.
- `article_number` nếu trích được.
- `ordinal`.

Các node metadata `LegalType`, `Authority`, `Sector` có thể giữ nếu đã có, nhưng không bắt buộc cho demo app.

### Edges

Document-Document:

- `AMENDS`: văn bản nguồn sửa đổi hoặc bổ sung văn bản đích.
- `CITES`: văn bản nguồn viện dẫn văn bản đích.
- `REPEALS`: văn bản nguồn bãi bỏ hoặc làm hết hiệu lực văn bản đích.
- `GUIDELINES`: văn bản nguồn hướng dẫn, quy định chi tiết văn bản đích.

Document-Article:

- `HAS_ARTICLE`: Document chứa Article.

Article-Article:

- `NEXT_ARTICLE`: Article kế tiếp trong cùng văn bản.
- `PARENT_OF`: tùy chọn nếu resolve được cấu trúc cha con.

Quy tắc chuẩn hóa:

- Loại cạnh nếu `doc_id` hoặc `other_doc_id` không có trong metadata.
- Loại self-loop.
- Đảo chiều quan hệ bị động để hướng cạnh luôn thống nhất.
- Gộp nhãn về 4 loại chính.
- Lưu `raw_relationship` và `confidence` nếu có để audit.

## 6. Backend API Contract for Frontend

### `GET /health`

Trả về trạng thái backend và kết nối phụ thuộc.

```json
{
  "status": "ok",
  "elasticsearch": "ok",
  "neo4j": "ok",
  "llm": "configured"
}
```

### `POST /search`

Dùng để FE hiển thị danh sách kết quả chưa cần LLM.

Request:

```json
{
  "query": "Điều kiện cấp giấy phép xây dựng là gì?",
  "retrieval_mode": "hybrid",
  "rerank": {
    "enabled": true,
    "model": "BAAI/bge-reranker-v2-m3",
    "candidate_k": 50,
    "batch_size": 8,
    "device": "auto"
  },
  "top_k": 5,
  "filters": {
    "effect_status": "Còn hiệu lực",
    "legal_type": ["Luật", "Nghị định"]
  },
  "include_graph": true
}
```

Response:

```json
{
  "query": "Điều kiện cấp giấy phép xây dựng là gì?",
  "retrieval_mode": "hybrid",
  "execution_mode": "hybrid_rerank",
  "latency_ms": 420,
  "results": [
    {
      "rank": 1,
      "chunk_id": "chunk:123:000004",
      "doc_id": "123",
      "title": "Luật Xây dựng",
      "document_number": "50/2014/QH13",
      "legal_type": "Luật",
      "effect_status": "Còn hiệu lực",
      "section_path": "Điều 89",
      "text": "Nội dung chunk...",
      "scores": {
        "dense": 0.81,
        "sparse": 14.2,
        "rrf": 0.032,
        "rerank": 0.71
      },
      "citation": "Luật Xây dựng 2014, Điều 89"
    }
  ],
  "graph_context": [
    {
      "doc_id": "456",
      "relation": "AMENDS",
      "target_doc_id": "123",
      "title": "Luật sửa đổi..."
    }
  ]
}
```

### `POST /answer`

Dùng cho chatbot. Backend tự retrieve, chọn context, gọi LLM và trả citation.

Request:

```json
{
  "query": "Văn bản nào đang sửa đổi quy định này?",
  "retrieval_mode": "hybrid",
  "rerank": {
    "enabled": true,
    "model": "BAAI/bge-reranker-v2-m3",
    "candidate_k": 50,
    "batch_size": 8,
    "device": "auto"
  },
  "top_k": 5,
  "filters": {
    "effect_status": "Còn hiệu lực"
  },
  "llm": {
    "temperature": 0.2,
    "max_context_chunks": 8
  },
  "graph": {
    "enabled": true,
    "use_lightrag": true,
    "max_hops": 1
  },
  "answer_style": "concise",
  "include_trace": true
}
```

Response:

```json
{
  "answer": "Câu trả lời tổng hợp...",
  "citations": [
    {
      "chunk_id": "chunk:123:000004",
      "doc_id": "123",
      "title": "Luật Xây dựng",
      "section_path": "Điều 89"
    }
  ],
  "retrieval_trace": {
    "retrieval_mode": "hybrid",
    "execution_mode": "hybrid_rerank",
    "dense_hits": 50,
    "sparse_hits": 50,
    "reranked": true,
    "temperature": 0.2,
    "graph_enabled": true,
    "lightrag_enabled": true
  },
  "latency_ms": 1200
}
```

### `GET /documents/{doc_id}/graph`

Dùng cho FE hiển thị quan hệ của một văn bản.

Query params:

- `depth`: mặc định `1`.
- `relations`: mặc định `AMENDS,CITES,REPEALS,GUIDELINES`.

Response:

```json
{
  "center": {
    "doc_id": "123",
    "title": "Luật Xây dựng"
  },
  "nodes": [
    {"id": "doc:123", "label": "Document", "title": "Luật Xây dựng"}
  ],
  "edges": [
    {"source": "doc:456", "target": "doc:123", "type": "AMENDS"}
  ]
}
```

### `GET /documents/{doc_id}/version-chain`

Trả chuỗi văn bản sửa đổi, bị sửa đổi, bãi bỏ.

Response:

```json
{
  "doc_id": "123",
  "chain": [
    {
      "doc_id": "100",
      "title": "Văn bản gốc",
      "relation_to_next": "AMENDS",
      "effect_date": "2014-01-01"
    }
  ]
}
```

## 7. LightRAG Integration

MVP sẽ xây dựng LightRAG như lớp orchestration, không để LightRAG thay thế toàn bộ retrieval stack hiện có.

Vai trò:

- Nhận query và phát hiện intent graph: hỏi về sửa đổi, bãi bỏ, dẫn chiếu, hướng dẫn, số hiệu văn bản cụ thể.
- Gọi `RetrievalService` để lấy candidates từ Elasticsearch theo 6 cấu hình retrieval.
- Gọi `GraphRetriever` để lấy quan hệ Neo4j khi query có tín hiệu graph hoặc khi `graph.enabled = true`.
- Hợp nhất context từ retrieval và graph trước khi gọi LLM.
- Trả về answer kèm citations, graph evidence và retrieval trace.

Thiết kế module:

- `LightRAGService.answer(request)`: entrypoint cho `/answer` khi `graph.use_lightrag = true`.
- `IntentDetector.detect(query)`: phát hiện document number, relation keywords và query type.
- `ContextAssembler.merge(retrieval_hits, graph_hits)`: deduplicate theo `chunk_id` và ưu tiên văn bản đúng số hiệu.
- `PromptBuilder.build(query, context, temperature_policy)`: dựng prompt có quy tắc không trả lời ngoài nguồn.

Nguyên tắc MVP:

- Nếu LightRAG lỗi, backend fallback sang retrieval + answer thường và trả `lightrag_enabled = false` trong trace.
- LightRAG không tự tạo schema KG mới. Schema nguồn vẫn là Neo4j MVP schema ở mục 5.
- Không cần dùng LightRAG để ingest dữ liệu nếu pipeline KG hiện tại đã tạo được Neo4j graph. Dùng LightRAG ở runtime orchestration trước.

Exit criteria:

- `/answer` chạy được với `graph.use_lightrag = true`.
- Query có số hiệu văn bản ưu tiên lấy đúng document và các Article liên quan.
- Query về sửa đổi, bãi bỏ, dẫn chiếu trả thêm graph evidence.
- Trace cho biết phần context nào đến từ dense, sparse, rerank và graph.

## 8. Neo4j Deployment Choice

Full KG theo audit trước có khoảng 7.8M nodes và 20M relationships. Với quy mô này, Neo4j AuraDB Free không phù hợp cho full graph vì giới hạn chính thức của bản Free thấp hơn rất nhiều. Thông tin Neo4j hiện tại cũng không hoàn toàn đồng nhất giữa các trang chính thức, nhưng cả hai mức giới hạn đều quá nhỏ so với KG của nhóm.

Nguồn kiểm tra ngày 2026-06-26:

- Neo4j AuraDB FAQ: AuraDB Free hỗ trợ tối đa 200k nodes và 400k relationships. Nguồn: `https://neo4j.com/cloud/platform/aura-graph-database/faq/`.
- Neo4j Free Graph Database FAQ: AuraDB Free ghi tối đa 50k nodes và 175k relationships. Nguồn: `https://neo4j.com/free-graph-database/`.

Khuyến nghị:

- Dùng Neo4j AuraDB Free chỉ cho subset demo nhỏ, ví dụ vài nghìn đến vài chục nghìn nodes, để FE và backend test luồng graph.
- Với full KG, dùng server tự host Neo4j Community hoặc Neo4j Enterprise nếu có license. Một VPS hoặc droplet có SSD và RAM đủ lớn thực tế hơn free cloud.
- Nếu muốn cloud managed cho full graph, dùng AuraDB paid tier, nhưng cần ước lượng chi phí và dung lượng trước khi import.
- Với MVP lớp học, lựa chọn hợp lý nhất là self-host Neo4j bằng Docker Compose trên server nhóm, hoặc local máy demo nếu không cần public URL.

Yêu cầu tài nguyên cần đo lại bằng import thật:

- SSD đủ chứa CSV import, database store và transaction logs.
- RAM đủ cho Neo4j page cache. Full graph Article lớn không nên chạy trên free tier.
- Tách Elasticsearch và Neo4j nếu cùng một máy bị thiếu RAM.

Quyết định MVP:

- Demo nội bộ: Docker Compose local hoặc server nhóm.
- Demo public ngắn hạn: FE public, Backend + Elasticsearch + Neo4j đặt trên một VPS nếu tài nguyên đủ.
- Neo4j Cloud Free: chỉ dùng cho subset graph, không dùng cho full KG.

## 9. KG Evaluation Criteria

### Structural correctness

Chạy trên artifact trước khi import Neo4j:

- `missing_endpoint_edges = 0` trong file importable edges.
- `self_loop_edges = 0`.
- `duplicate_document_ids = 0`.
- `duplicate_article_ids = 0`.
- `unknown_relation_ratio <= 1%` sau khi gộp 4 nhãn chính.
- `document_coverage >= 99%` so với metadata được chọn cho MVP.
- `article_coverage >= 95%` so với chunks được index vào Elasticsearch.
- `HAS_ARTICLE` count phải bằng số Article import được.

### Semantic correctness

Lấy mẫu thủ công:

- 50 cạnh `AMENDS`.
- 50 cạnh `CITES`.
- 30 cạnh `REPEALS`.
- 30 cạnh `GUIDELINES`.

Với mỗi cạnh, kiểm tra `source`, `target`, `type`, hướng cạnh, và trích đoạn metadata. Mục tiêu MVP:

- Precision edge type >= 90% cho `AMENDS`, `CITES`, `GUIDELINES`.
- Precision edge type >= 80% cho `REPEALS`, vì nhãn bãi bỏ/hết hiệu lực thường khó hơn.
- Direction accuracy >= 95%.

### Graph query correctness

Tạo gold nhỏ 20 đến 30 case:

- Với một văn bản, tìm văn bản sửa đổi nó.
- Với một văn bản, tìm văn bản nó dẫn chiếu.
- Với một văn bản, tìm văn bản bãi bỏ hoặc làm hết hiệu lực nó.
- Với một văn bản, lấy tất cả Article liên quan.

Metrics:

- `link_precision`.
- `link_recall`.
- `chain_exact_match`.
- `chain_contains_latest`.
- `article_recall@10`.

### Retrieval contribution

So sánh 7 cấu hình:

- Dense.
- Dense + Rerank.
- Sparse.
- Sparse + Rerank.
- Hybrid.
- Hybrid + Rerank.
- Hybrid + Rerank + Graph expansion.

Metrics:

- Hit@3, Hit@5, Hit@10.
- MRR@10.
- nDCG@10.
- Recall@10.
- Latency p50, p95.

MVP không yêu cầu graph luôn cải thiện global metrics. Chỉ cần chứng minh graph cải thiện nhóm query có nhắc rõ số hiệu văn bản, sửa đổi, bãi bỏ, viện dẫn.

### Performance

Mục tiêu demo:

- `/search` không gọi LLM: p50 dưới 700ms với ES và Neo4j đã warm.
- `/answer` có LLM: phụ thuộc provider, báo riêng retrieval latency và generation latency.
- Graph query 1-hop: dưới 300ms.
- Version chain depth 3: dưới 500ms.

## 10. Phase Plan

### Phase 0: Freeze MVP Scope

Deliverables:

- Chốt Elasticsearch là backend duy nhất cho dense và sparse.
- Chốt Neo4j chỉ dùng graph relations, không lưu vector.
- Chốt LightRAG là lớp runtime orchestration, không thay ingestion pipeline hiện có.
- Chốt frontend chỉ cần gọi API contract ở mục 6.
- Chốt demo dataset: full corpus nếu server đủ tài nguyên, hoặc subset có chọn lọc nếu không.

Exit criteria:

- `.env.example` có đủ biến ES, Neo4j, LLM.
- Nhóm thống nhất không đưa Qdrant vào MVP.
- Nhóm thống nhất Neo4j AuraDB Free chỉ dùng cho subset, không dùng cho full KG.

### Phase 1: Elasticsearch-Only Retrieval Cleanup

Tasks:

- Xóa hoặc deprecate `pipeline/04_embedding/build_qdrant.py`.
- Xóa hoặc deprecate `pipeline/04_embedding/upload_qdrant_turbo.py`.
- Gỡ `qdrant-client` khỏi root `requirements.txt`.
- Chỉnh `dense_retrieval.py` để đường chính chỉ còn Elasticsearch.
- Nếu vẫn muốn giữ FAISS để debug local, đặt tên rõ là fallback, không đưa vào app.
- Chuẩn hóa interface `Retriever.search(query, mode, filters, top_k, candidate_k)`.

Exit criteria:

- Dense ES query chạy được.
- Dense + rerank chạy được.
- Sparse ES query chạy được.
- Sparse + rerank chạy được.
- Hybrid RRF chạy được.
- Hybrid + rerank chạy được.
- Không còn hướng dẫn Qdrant trong README MVP.

### Phase 2: KG Cleaning and Rebuild

Tasks:

- Chuẩn hóa relationship label về `AMENDS`, `CITES`, `REPEALS`, `GUIDELINES`.
- Đảo chiều các quan hệ bị động.
- Loại orphan edge.
- Loại self-loop.
- Sửa `chunk_node_id` để không double-prefix.
- Đổi `Chunk` thành `Article` ở export Neo4j nếu nhóm muốn đồng nhất với spec. Nếu đổi gây rủi ro, giữ `Chunk` trong code nhưng API trả `Article`.
- Export typed CSV cho Document và Article thay vì chỉ `properties_json`.
- Tái sinh graph artifacts.
- Import Neo4j và chạy count verification.

Exit criteria:

- Import Neo4j thành công.
- Constraint trên `Document.id` và `Article.id`.
- Count Document, Article, HAS_ARTICLE, Document-Document edges được ghi vào report.
- Structural correctness đạt các ngưỡng ở mục 7.

### Phase 3: GraphRetriever and LightRAG

Tasks:

- Tạo module backend `graph_retriever`.
- Query theo `document_number` hoặc `doc_id`.
- Lấy neighbors 1-hop theo 4 loại quan hệ.
- Lấy version chain theo `AMENDS` và `REPEALS`.
- Lấy cited documents theo `CITES`.
- Lấy Article của các document liên quan.
- Trả JSON graph context cho API.
- Tạo `LightRAGService` để phối hợp RetrievalService, GraphRetriever và AnswerService.
- Thêm fallback khi LightRAG lỗi.

Exit criteria:

- `GET /documents/{doc_id}/graph` chạy được.
- `GET /documents/{doc_id}/version-chain` chạy được.
- Graph context merge được vào `/search` khi `include_graph = true`.
- `/answer` chạy được với `graph.use_lightrag = true`.

### Phase 4: Backend API

Tasks:

- Tạo FastAPI app riêng cho GraphRAG demo, không trộn với OCR Gradio nếu không cần.
- Implement `/health`, `/search`, `/answer`, `/documents/{doc_id}/graph`, `/documents/{doc_id}/version-chain`.
- Thêm request/response schema bằng Pydantic.
- Thêm timeout và error response rõ ràng.
- Log latency từng phần: dense, sparse, graph, rerank, LLM.
- Cache nhẹ bằng in-memory LRU cho query phổ biến và graph neighbors.

Exit criteria:

- FE có thể gọi API bằng JSON.
- Swagger UI hoạt động.
- Backend trả lỗi có cấu trúc, không dump stack trace.

### Phase 5: Frontend Handoff Spec

Frontend chỉ cần các màn hình:

- Search/chat box.
- Segmented control retrieval mode: Dense, Sparse, Hybrid.
- Toggle rerank: bật hoặc tắt.
- Rerank config panel: model, candidate_k, batch_size, device.
- Temperature slider: `0.0` đến `1.0`, mặc định `0.2`.
- Filter panel: hiệu lực, loại văn bản, lĩnh vực.
- Result list có citation.
- Answer panel.
- Document graph panel 1-hop.
- Debug panel tùy chọn để demo retrieval trace.

FE không cần:

- Tự gọi Elasticsearch.
- Tự gọi Neo4j.
- Tự rerank.
- Tự parse citation.

Exit criteria:

- FE render được response mẫu từ mục 6.
- FE handle loading, empty result, backend error.
- FE không phụ thuộc internal field ngoài API contract.

### Phase 6: Evaluation and Error Analysis

Tasks:

- Chuẩn hóa evaluation dataset hiện có sang JSONL gold.
- Chạy Dense, Dense + Rerank, Sparse, Sparse + Rerank, Hybrid, Hybrid + Rerank.
- Thêm nhóm query graph-specific.
- Chạy Hybrid + Rerank + Graph expansion cho nhóm graph-specific.
- Xuất bảng metrics và 10 lỗi tiêu biểu.
- Viết error analysis ngắn: lỗi do chunking, metadata, relation, rerank, hay LLM.

Exit criteria:

- Có bảng Hit@3, Hit@5, Hit@10, MRR@10, nDCG@10.
- Có KG link precision/recall.
- Có kết luận trung thực về KG giúp ở nhóm query nào và không giúp ở nhóm nào.

### Phase 7: Demo Deployment

Ưu tiên:

1. Local Docker Compose trên laptop/server nhóm.
2. Một VPS nhỏ nếu dữ liệu vừa tài nguyên.
3. FE trên Vercel/Netlify chỉ khi backend public ổn định.

Không khuyến nghị miễn phí hoàn toàn nếu chạy Neo4j + Elasticsearch full corpus, vì tài nguyên có thể vượt giới hạn free tier.

Docker Compose MVP gồm:

- `api`.
- `elasticsearch`.
- `neo4j`.
- `frontend` nếu nhóm không deploy riêng.

Exit criteria:

- Một lệnh chạy được demo stack.
- `/health` ok.
- Có script seed/import dữ liệu.
- Có checklist demo với 5 câu hỏi mẫu.

## 11. Revised Task Table

| Priority | Task | Keep, Modify, or Drop | Owner |
| --- | --- | --- | --- |
| P0 | Relationship Graph Cleaning | Keep and modify: bắt buộc thêm self-loop removal, endpoint validation, inverse direction, 4 labels | Backend/KG |
| P0 | Knowledge Graph Schema Design | Keep and simplify for MVP: Document, Article, 4 relation edges, HAS_ARTICLE | Backend/KG |
| P0 | Transform Relationships to Graph Edges | Keep: export CSV Neo4j, add typed fields, fix chunk id | Backend/KG |
| P0 | Load Graph into Neo4j | Keep: Docker Neo4j, import CSV, constraints, counts | Backend/KG |
| P0 | Elasticsearch Dense and Sparse Retrieval | Keep and consolidate: ES only | Backend |
| P0 | Hybrid Fusion Algorithm Design | Keep: RRF first, rerank optional | Backend |
| P0 | Metadata Filtering in Retrieval | Keep: effect_status, legal_type, sector | Backend |
| P0 | Backend API | Add: FastAPI for FE integration | Backend |
| P1 | Graph-Enhanced Hybrid Pipeline | Keep but narrow: trigger only when query mentions document number or relation intent | Backend/KG |
| P1 | Version Chain and Citation Queries | Keep: needed for demo graph | Backend/KG |
| P1 | Evaluation Dataset | Keep: use existing dataset plus graph-specific cases | Evaluation |
| P1 | Error Analysis | Keep: short report for presentation | Evaluation |
| P1 | Frontend API Spec | Add: FE reads API contract, does not own retrieval logic | Backend/FE |
| P2 | Query Latency and Caching | Modify: simple LRU and parallel dense/sparse, target demo latency | Backend |
| P2 | Containerization | Keep: docker-compose MVP only | Infra |
| P1 | LightRAG Integration | Keep: runtime orchestration over ES retrieval and Neo4j graph, with fallback | Backend |
| P3 | Scalability for Document Updates | Defer: describe future work | Infra |
| P3 | CI/CD and Monitoring | Defer: only basic GitHub Actions test if time | Infra |
| P3 | Production Deployment | Defer: demo deployment only | Infra |
| P3 | Stress test 100 request/s | Drop from MVP | Infra |

## 12. Demo Success Criteria

MVP được xem là đạt nếu demo được các tình huống sau:

- Người dùng hỏi một câu pháp luật và nhận câu trả lời có citation.
- Người dùng đổi retrieval mode Dense, Sparse, Hybrid, bật/tắt rerank và thấy execution mode tương ứng trong trace.
- Người dùng chỉnh temperature và backend truyền đúng cấu hình vào LLM.
- Người dùng bật LightRAG và thấy graph evidence trong câu trả lời khi query có tín hiệu quan hệ pháp lý.
- Người dùng bật lọc `Còn hiệu lực` và kết quả chỉ trả về văn bản còn hiệu lực.
- Người dùng nhập hoặc chọn một văn bản cụ thể và xem được quan hệ sửa đổi, dẫn chiếu, bãi bỏ, hướng dẫn.
- Backend trả retrieval trace để nhóm giải thích vì sao hệ thống chọn nguồn.
- Có bảng evaluation so sánh các mode retrieval.
- Có báo cáo KG quality, bao gồm structural checks và sampled semantic checks.

## 13. Immediate Backend Checklist

- [ ] Tách app GraphRAG backend khỏi app OCR demo hoặc đặt rõ hai entrypoint.
- [ ] Xóa/deprecate Qdrant scripts và dependency khỏi MVP.
- [ ] Chuẩn hóa `DenseRetriever` sang Elasticsearch-only path.
- [ ] Viết `SparseRetriever` hoặc wrapper dùng ES BM25 hiện có.
- [ ] Viết `FusionRetriever` dùng RRF.
- [ ] Viết `RerankService`.
- [ ] Viết `GraphRetriever`.
- [ ] Viết `LightRAGService` và fallback path.
- [ ] Viết FastAPI schemas và endpoints.
- [ ] Viết Docker Compose cho ES, Neo4j, API.
- [ ] Viết evaluation report cho Dense, Dense + Rerank, Sparse, Sparse + Rerank, Hybrid, Hybrid + Rerank, Graph-specific.
