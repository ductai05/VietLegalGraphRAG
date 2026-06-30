# MVP Phase Backlog Spec: Backend, Infrastructure, Knowledge Graph

## 1. Purpose

Tài liệu này cụ thể hóa phạm vi MVP demo của VietLegalGraphRAG thành các phase có thể chia task cho nhóm. Trọng tâm là Backend, Knowledge Graph, retrieval service, hạ tầng demo và handoff contract cho Frontend.

Mục tiêu demo là một hệ thống hỏi đáp pháp luật có thể trình bày cho một giảng viên:

1. Người dùng nhập câu hỏi.
2. Backend chạy retrieval theo chế độ được chọn: Dense, Sparse hoặc Hybrid.
3. Người dùng có thể bật hoặc tắt rerank.
4. Khi câu hỏi có tín hiệu văn bản pháp lý cụ thể hoặc quan hệ pháp lý, backend mở rộng bằng Knowledge Graph.
5. Backend sinh câu trả lời có citation và graph evidence.
6. Frontend hiển thị answer, sources, retrieval trace và graph context mà không cần gọi trực tiếp Elasticsearch hoặc Neo4j.

Tài liệu này không thay thế các spec kiến trúc trước đó. Nó là backlog triển khai từ trạng thái repo hiện tại đến MVP demo.

## 2. Out of Scope and Non-goals

Các mục sau không thuộc MVP demo:

- Stress test 100 request/s.
- CI/CD production đầy đủ với build image, push registry, deploy tự động.
- Prometheus, Grafana và alerting production.
- Multi-tenant authentication, RBAC hoặc user management.
- Incremental update không dừng hệ thống cho toàn bộ corpus.
- Neo4j AuraDB Free cho full KG.
- Vector storage trong Neo4j.
- Qdrant trong runtime MVP.
- Local PaddleOCR trong runtime MVP.
- Frontend tự xử lý retrieval, rerank, graph query hoặc citation parsing.
- Tối ưu cost cloud ở mức production.
- Cam kết latency dưới 500ms cho `/answer` có gọi LLM. MVP chỉ cần tách rõ retrieval latency và generation latency.

Các tài liệu Qdrant lịch sử có thể giữ lại nếu được đánh dấu là historical, nhưng không được xuất hiện trong README hoặc hướng dẫn chạy MVP như một bước bắt buộc.

## 3. Current State

### Existing Assets

Repo hiện có các tài sản dùng được cho MVP:

- `pipeline/05_graph/schema.py`
  - Có `NormalizedRelationship`.
  - Có canonical edge types: `AMENDS`, `CITES`, `REPEALS`, `GUIDELINES`.
  - Có `raw_label` trong `EDGE_FIELDS`.
  - Có `reverse_direction` cho quan hệ bị động.

- `pipeline/05_graph/build_graph.py`
  - Build node `Document`, node `Chunk`, metadata nodes và relationship edges.
  - Loại relationship có endpoint không tồn tại trong metadata.
  - Loại self-loop.
  - Đảo chiều quan hệ bị động.
  - Lưu `raw_label` và `raw_relationship` trong properties.
  - Fix double-prefix cho `chunk_node_id`.
  - Export CSV và `neo4j_import.cypher`.

- `tests/test_knowledge_graph.py`
  - Có test cho normalize relationship.
  - Có test kiểm tra `raw_label` được preserve khi export và trong Neo4j Cypher.

- `src/backend/services/retrieval_modes.py`
  - Có request model dạng dataclass cho `retrieval_mode`, `rerank`, `llm`, `graph`.
  - Có 6 execution modes suy ra từ Dense, Sparse, Hybrid kết hợp bật hoặc tắt rerank.
  - Có validation cho temperature, top_k, candidate_k.

- `src/backend/services/lightrag_service.py`
  - Có lớp orchestration sơ bộ giữa `RetrievalService`, `GraphRetriever`, `AnswerService`.
  - Có fallback khi graph retrieval lỗi.
  - Có merge context theo retrieval và graph.

- `pipeline/04_embedding/dense_retrieval.py`
  - Đã reject Qdrant target trong MVP dense retrieval.

- `pipeline/05_sparse_retrieval`
  - Có pipeline sparse retrieval bằng Elasticsearch.

- `pipeline/07_evaluation`
  - Có script evaluation retrieval, hybrid search, rerank, error analysis.
  - Có output evaluation hiện có trong `output/`.

- `src/`
  - Đã có nhánh `src/backend`, `src/frontend`, `src/infra` ở mức skeleton hoặc README.

### Known Gaps

Các khoảng trống còn phải xử lý:

- Chưa có FastAPI app trong `src/backend` cho GraphRAG MVP.
- Chưa có implementation `GraphRetriever` thật dùng Neo4j driver.
- Chưa có service retrieval thống nhất gọi Dense ES, Sparse ES, Hybrid RRF và rerank từ một interface backend.
- Chưa có `AnswerService` thật để gọi LLM và trả citation theo contract.
- Chưa có Docker Compose MVP dưới `src/infra`.
- Chưa có `.env.example` chuẩn cho ES, Neo4j, LLM, reranker.
- Chưa có Neo4j import run mới từ artifact hiện tại.
- Chưa có report audit KG mới sau khi đã thêm `raw_label`, self-loop removal và canonical labels.
- Chưa có API contract đủ chi tiết trong `src/frontend` để FE implement.
- Chưa có endpoint `/search`, `/answer`, `/documents/{doc_id}/graph`, `/documents/{doc_id}/version-chain`.
- Chưa có evaluation riêng cho graph-specific queries.
- Còn nhiều tài liệu lịch sử nhắc Qdrant, dễ gây hiểu nhầm nếu thành viên mới đọc.
- Node Article trong spec nghiệp vụ hiện vẫn là `Chunk` trong code. MVP cần quyết định đổi label trong graph hay chỉ map `Chunk` thành Article ở API.

## 4. Guiding Principles

- ES-only retrieval: Dense và Sparse đều chạy qua Elasticsearch trong runtime MVP.
- Elasticsearch Cloud là retrieval backend duy nhất cho runtime MVP.
- Neo4j chạy trên VPS riêng và là graph store cho legal relationships và document-article traversal.
- OCR dùng Google Cloud Vision như external managed service.
- LightRAG trong MVP là runtime orchestration, không thay ingestion pipeline.
- KG không thay thế Dense hoặc Sparse retrieval. KG bổ sung provenance, graph expansion, version chain và legal relation queries.
- FE chỉ consume backend API. FE không biết chi tiết Elasticsearch, Neo4j, reranker hoặc LLM provider.
- Ưu tiên demo reproducible hơn production completeness.
- Giữ raw legal semantics bằng `raw_label`, nhưng query traversal dùng canonical edge type.
- Mỗi phase phải có deliverable cụ thể để tạo issue và nghiệm thu.

## 5. Decisions

### Decided

- Runtime retrieval chỉ dùng Elasticsearch cho Dense và Sparse.
- Elasticsearch runtime target là Elasticsearch Cloud.
- Retrieval modes trong FE là `dense`, `sparse`, `hybrid`.
- Rerank là toggle riêng. Backend suy ra 6 execution modes:
  - `dense`
  - `dense_rerank`
  - `sparse`
  - `sparse_rerank`
  - `hybrid`
  - `hybrid_rerank`
- Temperature là tham số LLM answer, không phải tham số retrieval quality.
- KG dùng canonical relationship types: `AMENDS`, `CITES`, `REPEALS`, `GUIDELINES`.
- KG phải preserve `raw_label` trên edge.
- Qdrant không thuộc runtime MVP.
- Neo4j chạy trên dedicated VPS cho MVP graph.
- MVP graph traversal giữ ở one-hop.
- OCR dùng Google Cloud Vision API với Google Service Account JSON credential.
- Local PaddleOCR không thuộc runtime MVP.
- LightRAG chỉ là orchestration layer, không thay thế retrieval.
- `ExtractiveAnswerService` vẫn là implementation hiện tại; LLM-backed `AnswerService` là thay thế tương lai qua cùng contract.
- Temperature default là `0.2`.

### Final Runtime Pipeline

```text
User Query
  -> Intent Detection
  -> Hybrid Elasticsearch Retrieval (Dense + Sparse)
  -> RRF
  -> Optional Rerank
  -> Document Resolution
  -> Optional Neo4j Graph Expansion
  -> Context Assembly
  -> LLM Answer
  -> Citation + Trace
```

`Document Resolution` trong pipeline nÃ y lÃ  logical orchestration step. Module riÃªng `DocumentResolver` váº«n lÃ  future enhancement vÃ  khÃ´ng Ä‘Æ°á»£c schedule trÆ°á»›c khi hoÃ n táº¥t MVP hiá»‡n táº¡i.

### Graph Expansion Policy

| Query intent | Graph expansion |
| --- | --- |
| General question | one-hop neighbors |
| Amendment | `AMENDS` |
| Repeal | `REPEALS` |
| Citation | `CITES` |
| Guideline | `GUIDELINES` |

### Deployment Decisions

- Elasticsearch: cloud deployment.
- Neo4j: dedicated VPS.
- OCR: Google Vision API.
- Reranker provider: evaluate Jina AI and Voyage AI; do not select one before MVP completion.

Current Neo4j VPS profile:

- 2 vCPU.
- Approximately 2 to 2.4 GB RAM available.
- 8 GB swap.
- zRAM enabled.
- Approximately 24 GB free disk.

### Future Enhancements Only

Các thành phần sau chỉ là future enhancements và không được schedule trước khi hoàn tất MVP hiện tại:

- `QueryPlanner`
- `DocumentResolver`
- `ContextBudgetManager`
- `CitationVerifier`
- `RetrievalTraceLogger`
- Cache

### Pending Decisions

- `Chunk` vs `Article` label:
  - Option 1: Đổi Neo4j label từ `Chunk` sang `Article`.
  - Option 2: Giữ `Chunk` trong internal graph, API trả field và label là Article.
  - Khuyến nghị MVP: chọn Option 2 để giảm rủi ro migration, sau demo có thể đổi schema sạch hơn.

- Demo graph size:
  - Option 1: Full corpus nếu server đủ RAM và SSD.
  - Option 2: Subset theo lĩnh vực hoặc top legal types để chạy ổn định.
  - Khuyến nghị MVP: chuẩn bị cả subset smoke graph và full graph path. Demo dùng subset nếu full import không ổn định.

- Deployment target:
  - Đã chốt: Elasticsearch Cloud, Neo4j dedicated VPS, OCR qua Google Vision API.
  - Docker Compose Task 10 chỉ đóng gói API demo container và cấu hình kết nối ra external services.
  - FE public trên Vercel hoặc Netlify nếu backend có public URL.

## 6. Service Interface Contracts

Các module backend phải phát triển độc lập qua contract rõ ràng. Implementation có thể dùng dataclass ở service layer và Pydantic ở API layer, nhưng tên field nên đồng nhất.

### RetrievalRequest

Inputs:

- `query: str`
- `retrieval_mode: "dense" | "sparse" | "hybrid"`
- `rerank.enabled: bool`
- `rerank.model: str`
- `rerank.candidate_k: int`
- `rerank.batch_size: int`
- `rerank.device: "auto" | "cpu" | "cuda"`
- `rerank.timeout_ms: int`
- `top_k: int`
- `filters: dict`
- `graph.enabled: bool`
- `graph.use_lightrag: bool`
- `graph.max_hops: int`
- `llm.temperature: float`
- `llm.max_context_chunks: int`
- `include_trace: bool`

Derived field:

- `execution_mode: "dense" | "dense_rerank" | "sparse" | "sparse_rerank" | "hybrid" | "hybrid_rerank"`

### RetrievalHit

Required output fields:

- `rank: int`
- `chunk_id: str`
- `doc_id: str`
- `title: str`
- `document_number: str`
- `legal_type: str`
- `effect_status: str`
- `section_path: str`
- `text: str`
- `scores: dict`
- `citation: str`

Scores should use stable keys where available:

- `dense`
- `sparse`
- `rrf`
- `rerank`

### GraphContext

GraphRetriever returns:

- `center: dict | None`
- `nodes: list[dict]`
- `edges: list[dict]`
- `related_chunks: list[dict]`
- `query_intent: str`

Each graph edge should include:

- `source`
- `target`
- `type`
- `raw_label`
- `direction`

### AnswerContext

LightRAG and AnswerService consume merged contexts:

- `source: "retrieval" | "graph"`
- `chunk_id: str | None`
- `doc_id: str`
- `title: str`
- `text: str`
- `citation: str`
- `relation: str | None`
- `raw_label: str | None`

### API Response Envelope

All user-facing endpoints should return:

- `latency_ms`
- data payload specific to endpoint.
- `trace` or `retrieval_trace` when requested.
- `warnings: list[str]` for degraded but usable responses.

Error responses should use:

- `error.code`
- `error.message`
- `error.retryable`
- `trace_id`

## 7. Phase Dependency Map

```text
Phase 0: Scope Freeze
  -> Phase 1: KG Artifact Audit and Rebuild
  -> Phase 2: Neo4j Import and Graph Verification
  -> Phase 4: GraphRetriever

Phase 0: Scope Freeze
  -> Phase 3: Retrieval Services Consolidation
  -> Phase 6a: FastAPI Search and Health

Phase 3 + Phase 4
  -> Phase 5: LightRAG Runtime Orchestration
  -> Phase 6b: FastAPI Answer and Graph Endpoints

Phase 6: FastAPI Backend
  -> Phase 7: Frontend Contract Handoff
  -> Phase 9: Demo Script and Final QA

Phase 1, Phase 2, Phase 3
  -> Phase 8: Evaluation and Error Analysis

Phase 6
  -> Phase 10: Infrastructure and Deployment
  -> Phase 9: Demo Script and Final QA
```

### Can Run in Parallel

- Phase 1 and Phase 3 can run in parallel after Phase 0.
- Phase 6a can start after Phase 3 without waiting for LightRAG.
- Phase 7 can start from mocked API response before Phase 6b is fully complete.
- Phase 8 can start with existing output files, then rerun after Phase 1 to Phase 6 stabilize.
- Phase 10 can start with skeleton Docker Compose while API endpoints are still being implemented.

### Must Be Sequential

- Phase 2 depends on Phase 1 artifacts.
- Phase 4 depends on Phase 2 or at least a smoke Neo4j graph.
- Phase 5 depends on Phase 3 and Phase 4 interfaces.
- Phase 6a depends on Phase 3.
- Phase 6b `/answer` depends on Phase 5.
- Phase 6b graph endpoints depend on Phase 4.
- Phase 9 depends on Phase 6 and at least one working deployment mode.

### Criteria Semantics

- Acceptance Criteria kiểm tra hành vi hoặc output của phase đó.
- Exit Criteria là điều kiện để phase phụ thuộc phía sau có thể bắt đầu an toàn.
- Nếu một phase có cùng một điều kiện ở cả hai nhóm, Acceptance Criteria kiểm chứng điều kiện đó, còn Exit Criteria dùng điều kiện đó như gate chuyển tiếp.

## 8. Phase Backlog

### Phase 0: Scope Freeze and Repo Baseline

Goal:

Chốt phạm vi MVP, biến các quyết định hiện có thành cấu hình repo rõ ràng để nhóm không làm trùng hoặc đi lệch hướng.

Inputs and Dependencies:

- Spec hiện tại trong `docs/superpowers/specs/2026-06-26-mvp-backend-infra-kg-spec.md`.
- Các dịch vụ sơ bộ trong `src/backend/services`.
- Pipeline retrieval và KG hiện có.

Tasks:

- Tạo hoặc cập nhật `.env.example` cho:
  - `ELASTICSEARCH_URL`
  - `ELASTICSEARCH_API_KEY`
  - `NEO4J_URI`
  - `NEO4J_USER`
  - `NEO4J_PASSWORD`
  - `LLM_PROVIDER`
  - `LLM_API_KEY`
  - `RERANK_MODEL`
  - `DEFAULT_RETRIEVAL_MODE`
  - `DEFAULT_TEMPERATURE`
- Cập nhật README MVP để ghi rõ:
  - ES là backend duy nhất cho dense và sparse runtime.
  - Qdrant là historical, không dùng trong MVP.
  - Neo4j Free Cloud chỉ dùng subset.
  - FE gọi API backend, không gọi ES hoặc Neo4j.
- Chọn chiến lược demo graph:
  - `subset` cho smoke/demo ổn định.
  - `full` nếu server đủ tài nguyên.
- Chốt quy ước `Chunk` vs `Article` cho MVP.

Files to Create or Modify:

- `.env.example`
- `README.md`
- `src/README.md`
- `src/backend/README.md`
- `src/frontend/README.md`
- `src/infra/README.md`

Deliverables and Outputs:

- Scope note ngắn trong README.
- Env template đủ để chạy local.
- Decision log cho `Chunk` vs `Article` và graph size.

Acceptance Criteria:

- Thành viên mới đọc README không cần Qdrant để chạy MVP.
- Có thể cấu hình ES, Neo4j, LLM từ `.env`.
- Nhóm thống nhất dataset demo trước khi import Neo4j.

Exit Criteria:

- README và `.env.example` không mâu thuẫn với spec MVP.
- Không còn task P0 nào phụ thuộc Qdrant.

Owner Suggestion:

- Backend lead và Infra lead.

Risks:

- Nếu không chốt graph size sớm, Phase 2 có thể bị kẹt vì full KG quá lớn cho máy demo.

### Phase 1: KG Artifact Audit and Rebuild

Goal:

Đánh giá KG hiện tại theo invariant MVP, rebuild graph artifacts sạch và tạo report chất lượng trước khi import Neo4j.

Inputs and Dependencies:

- `data/preprocessed/metadata.parquet`
- `data/preprocessed/relationships.parquet`
- chunk output nếu đã có.
- `pipeline/05_graph/schema.py`
- `pipeline/05_graph/build_graph.py`

Tasks:

- Chạy unit test KG hiện có.
- Build smoke graph bằng `--limit` để kiểm tra nhanh.
- Build subset graph demo theo phạm vi được chốt.
- Nếu tài nguyên cho phép, build full graph artifact.
- Audit các chỉ số:
  - document count
  - chunk count
  - edge count by type
  - raw relationship distribution
  - orphan relationship count
  - self-loop relationship count
  - duplicate node count
  - duplicate edge count
  - missing `raw_label`
- Kiểm tra invariant:
  - Document edge chỉ thuộc 4 canonical types.
  - `raw_label` tồn tại cho Document-Document edges.
  - Không có self-loop trong importable edges.
  - Không có endpoint document thiếu metadata trong importable edges.
  - `chunk_node_id` không bị double-prefix.
- Nếu artifact chưa có typed properties đủ dùng cho query, mở task riêng ở Phase 1 hoặc Phase 2 để bổ sung.
- Viết `kg_quality_report.md`.

Files to Create or Modify:

- `pipeline/05_graph/build_graph.py`
- `pipeline/05_graph/schema.py`
- `pipeline/05_graph/README.md`
- `output/kg_quality/kg_quality_report.md`
- `output/kg_quality/kg_quality_summary.json`
- `data/graph/` hoặc `data/processed/neo4j_imports/` tùy đường dẫn được chốt.

Deliverables and Outputs:

- Rebuilt graph artifacts.
- KG quality report.
- Smoke graph artifact có thể import nhanh.
- Nếu có full graph, full graph artifact kèm count report.

Acceptance Criteria:

- `missing_endpoint_edges = 0` trong importable document relationship edges.
- `self_loop_edges = 0` trong importable document relationship edges.
- 100% Document-Document edges có `type` thuộc `AMENDS`, `CITES`, `REPEALS`, `GUIDELINES`.
- 100% Document-Document edges có `raw_label`.
- `duplicate_document_ids = 0`.
- `duplicate_article_or_chunk_ids = 0` trong artifact được import.
- Có report ghi rõ số edge bị loại vì orphan hoặc self-loop.

Exit Criteria:

- KG đủ sạch để import Neo4j.
- Nhóm biết rõ đang demo bằng subset hay full graph.

Owner Suggestion:

- KG engineer.

Risks:

- Full KG có thể quá lớn cho storage hoặc RAM local.
- Chunks có thể chưa đồng bộ với dense/sparse index, gây mismatch khi graph expansion trả Article.

### Phase 2: Neo4j Import and Graph Verification

Goal:

Đưa graph artifact vào Neo4j và xác minh truy vấn graph quan trọng chạy được với latency demo chấp nhận được.

Inputs and Dependencies:

- Phase 1 graph artifacts.
- Neo4j local Docker hoặc Neo4j server.
- `neo4j_import.cypher` hoặc script bulk import.

Tasks:

- Chọn import mode:
  - Smoke/subset: `LOAD CSV` qua Cypher.
  - Full graph: ưu tiên `neo4j-admin database import` nếu CSV lớn.
- Tạo constraint và index:
  - `Document.id`
  - `Document.doc_id` nếu typed property tồn tại.
  - `Document.document_number` nếu typed property tồn tại.
  - `Chunk.id` hoặc `Article.id`.
  - `Chunk.chunk_id` hoặc `Article.chunk_id`.
- Import nodes và relationships.
- Chạy verification Cypher:
  - Count node by label.
  - Count edge by type.
  - Sample edges có `raw_label`.
  - Query neighbors 1-hop.
  - Query version chain theo `AMENDS`, `REPEALS`.
  - Query cited docs theo `CITES`.
  - Query articles hoặc chunks của một document.
- Ghi `neo4j_import_report.md`.
- Nếu dùng Neo4j AuraDB Free, chỉ import subset và ghi rõ giới hạn.

Files to Create or Modify:

- `pipeline/05_graph/neo4j_import.cypher`
- `pipeline/05_graph/import_and_verify.ps1`
- `src/infra/docker-compose.yml`
- `docs/neo4j_local_guide.md`
- `output/kg_quality/neo4j_import_report.md`

Deliverables and Outputs:

- Neo4j database chạy được.
- Import report với counts và sample query results.
- Verification script hoặc command list tái chạy được.

Acceptance Criteria:

- `/health` tương lai có thể kiểm tra Neo4j connection.
- Neo4j có đủ 4 relationship types chính.
- Graph query 1-hop trên subset demo trả kết quả dưới 300ms sau warmup.
- Version chain depth 3 trả kết quả dưới 500ms trên subset demo.
- Sample edge có property `raw_label`.

Exit Criteria:

- Có URI, username, password và database name để Backend dùng.
- Có ít nhất 5 document sample dùng được cho demo graph.

Owner Suggestion:

- KG engineer và Infra lead.

Risks:

- `LOAD CSV` có thể chậm hoặc lỗi memory với full graph.
- Neo4j cần APOC nếu tiếp tục dùng dynamic relationship creation.
- Typed properties chưa được tách khỏi `properties_json` sẽ làm query phức tạp hơn.

### Phase 3: Retrieval Services Consolidation

Goal:

Đóng gói Dense, Sparse, Hybrid và Rerank thành một backend service thống nhất, dùng Elasticsearch cho cả Dense và Sparse.

Inputs and Dependencies:

- `pipeline/04_embedding/dense_retrieval.py`
- `pipeline/05_sparse_retrieval`
- `pipeline/07_evaluation/hybrid_search.py`
- `src/backend/services/retrieval_modes.py`

Tasks:

- 3.1. Thiết kế service interface:
  - `search(request: RetrievalRequest) -> list[RetrievalHit]`
  - `RetrievalHit` có `chunk_id`, `doc_id`, `title`, `text`, metadata, scores, citation.
- 3.2. Implement Dense ES adapter:
  - dùng index dense Elasticsearch.
  - nhận metadata filters.
  - trả `RetrievalHit` với `scores.dense`.
- 3.3. Implement Sparse ES adapter:
  - dùng BM25 Elasticsearch.
  - nhận metadata filters cùng schema với Dense adapter.
  - trả `RetrievalHit` với `scores.sparse`.
- 3.4. Implement FusionRetriever:
  - chạy dense và sparse song song.
  - merge theo `chunk_id`.
  - tính `scores.rrf`.
  - preserve score gốc để trace.
- 3.5. Implement RerankService:
  - nhận candidates từ dense, sparse hoặc hybrid.
  - batch theo `rerank.batch_size`.
  - timeout theo `rerank.timeout_ms`.
  - trả `scores.rerank`.
- 3.6. Implement RetrievalService:
  - resolve `execution_mode`.
  - gọi adapter tương ứng.
  - apply top_k sau rerank hoặc fusion.
  - chuẩn hóa citation.
- 3.7. Chuẩn hóa filter propagation:
  - `effect_status`
  - `legal_type`
  - `linh_vuc` hoặc `legal_sectors`
  - `issuing_authority`
  - optional date range.
- 3.8. Viết tests và smoke command.
- Implement hoặc wrap nếu muốn tái sử dụng code hiện có:
  - `DenseElasticsearchRetriever`
  - `SparseElasticsearchRetriever`
  - `FusionRetriever` dùng RRF.
  - `RerankService`.
  - `RetrievalService`.
- Chuẩn hóa score trace:
  - `dense`
  - `sparse`
  - `rrf`
  - `rerank`.
- Đảm bảo 6 execution modes hoạt động.
- Update docs để Qdrant không còn là runtime path.

Files to Create or Modify:

- `src/backend/services/retrieval_service.py`
- `src/backend/services/retrieval_modes.py`
- `src/backend/services/rerank_service.py`
- `pipeline/04_embedding/dense_retrieval.py`
- `pipeline/05_sparse_retrieval/README.md`
- tests dưới `tests/`.

Deliverables and Outputs:

- Retrieval service importable từ FastAPI.
- Unit tests cho mode resolution, filter propagation, RRF và rerank toggle.
- Smoke command hoặc test dùng mocked ES client.

Acceptance Criteria:

- `dense` trả kết quả từ dense ES.
- `dense_rerank` rerank candidate từ dense ES.
- `sparse` trả kết quả từ BM25 ES.
- `sparse_rerank` rerank candidate từ BM25 ES.
- `hybrid` merge dense và sparse bằng RRF.
- `hybrid_rerank` rerank sau RRF.
- `rerank.candidate_k >= top_k` được validate.
- Filter `effect_status = Còn hiệu lực` được truyền xuống ES query.

Exit Criteria:

- FastAPI có thể gọi một service duy nhất cho `/search`.
- Không có runtime import bắt buộc tới Qdrant.

Owner Suggestion:

- Backend retrieval engineer.

Risks:

- Dense index và sparse index có thể dùng field metadata khác tên nhau.
- Reranker có thể chậm trên CPU, cần timeout và candidate_k thực tế.

### Phase 4: GraphRetriever

Goal:

Tạo service backend truy vấn Neo4j để lấy graph context, version chain, citation relations và Article chunks liên quan.

Inputs and Dependencies:

- Phase 2 Neo4j database.
- `src/backend/services/lightrag_service.py` protocol `GraphRetriever`.

Tasks:

- Tạo `src/backend/services/graph_retriever.py`.
- Implement Neo4j connection lifecycle.
- Implement query theo:
  - `doc_id`
  - `document_number`
  - `chunk_id` từ retrieval hit.
- Implement functions:
  - `get_document_neighbors(doc_id, relations, depth)`
  - `get_version_chain(doc_id)`
  - `get_cited_documents(doc_id)`
  - `get_guideline_documents(doc_id)`
  - `get_document_articles(doc_id, limit)`
  - `retrieve(query, retrieval_hits, max_hops)`
- Detect document number trong query bằng rule đơn giản.
- Deduplicate graph hits theo `chunk_id` hoặc `(doc_id, relation_type)`.
- Trả `raw_label` cùng canonical relation type.
- Thêm timeout và fallback empty result.

Files to Create or Modify:

- `src/backend/services/graph_retriever.py`
- `src/backend/services/graph_models.py`
- `tests/test_graph_retriever.py`
- `src/backend/README.md`

Deliverables and Outputs:

- GraphRetriever service chạy với Neo4j.
- JSON graph context thống nhất cho API và LightRAG.
- Tests bằng fake Neo4j session hoặc mocked records.

Acceptance Criteria:

- Query document by `doc_id` trả center node.
- Query by `document_number` resolve được document nếu property tồn tại.
- 1-hop graph trả nodes, edges, relation type và `raw_label`.
- Version chain trả danh sách có thứ tự đủ dùng demo.
- Citation query trả cited docs và Article chunks liên quan nếu có.
- GraphRetriever failure không làm sập `/answer`.

Exit Criteria:

- LightRAGService có thể dùng GraphRetriever thật thay vì fake.
- API graph endpoints có thể build trên service này.

Owner Suggestion:

- Backend/KG engineer.

Risks:

- Nếu Neo4j chỉ có `properties_json`, query theo `document_number` sẽ kém hiệu quả. Cần typed properties hoặc fallback resolve từ ES.

### Phase 5: LightRAG Runtime Orchestration

Goal:

Hoàn thiện LightRAGService thành lớp orchestration runtime kết hợp retrieval, graph expansion, answer generation và trace.

Inputs and Dependencies:

- Phase 3 RetrievalService.
- Phase 4 GraphRetriever.
- AnswerService hoặc LLM adapter.
- `src/backend/services/lightrag_service.py`.

Tasks:

- Tách intent detection:
  - query hỏi sửa đổi, bổ sung.
  - query hỏi bãi bỏ, hết hiệu lực.
  - query hỏi căn cứ, dẫn chiếu.
  - query có số hiệu văn bản.
- Định nghĩa rule graph expansion:
  - Nếu query có số hiệu văn bản, ưu tiên resolve document và lấy Article liên quan.
  - Nếu query có relation intent, gọi relation query tương ứng.
  - Nếu `graph.enabled = false`, không gọi Neo4j.
  - Nếu `graph.use_lightrag = false`, dùng retrieval thường.
- Merge context:
  - Retrieval hits giữ thứ hạng chính.
  - Graph hits được thêm nếu liên quan doc hoặc relation intent.
  - Deduplicate theo `chunk_id`.
  - Ưu tiên exact document match.
- Build prompt policy:
  - Chỉ trả lời dựa trên context.
  - Trích citation theo chunk hoặc document.
  - Nêu thiếu thông tin nếu context không đủ.
- Trả retrieval trace:
  - retrieval mode
  - execution mode
  - reranked
  - temperature
  - dense hits
  - sparse hits
  - graph hits
  - lightrag enabled
  - fallback reason nếu có.

Files to Create or Modify:

- `src/backend/services/lightrag_service.py`
- `src/backend/services/intent_detector.py`
- `src/backend/services/context_assembler.py`
- `src/backend/services/answer_service.py`
- `tests/test_lightrag_service.py`

Deliverables and Outputs:

- LightRAG runtime path dùng được cho `/answer`.
- Unit tests cho fallback, graph enabled/disabled và context merge.
- Trace đủ để demo và debug.

Acceptance Criteria:

- Query thường chạy retrieval + answer.
- Query có số hiệu văn bản gọi graph path.
- Query relation intent trả graph evidence.
- LightRAG lỗi thì fallback sang retrieval answer và trace có `lightrag_enabled = false`.
- Temperature trong request được truyền vào AnswerService.

Exit Criteria:

- `/answer` có thể expose `graph.use_lightrag`.
- FE có thể hiển thị graph evidence và trace.

Owner Suggestion:

- Backend orchestration engineer.

Risks:

- Dùng từ khóa intent quá đơn giản có thể miss query tự nhiên. MVP chấp nhận rule-based, sau demo cải tiến bằng classifier.

### Phase 6: FastAPI Backend

Goal:

Xây dựng backend API cho FE và demo, bọc RetrievalService, GraphRetriever, LightRAGService và health checks.

Inputs and Dependencies:

- Phase 3, Phase 4, Phase 5.
- Existing `src/backend` skeleton.

Tasks:

- 6.1. Tạo FastAPI app trong `src/backend/app`.
- 6.2. Tạo Pydantic schemas cho:
  - `SearchRequest`
  - `AnswerRequest`
  - `RerankConfig`
  - `LLMConfig`
  - `GraphConfig`
  - `RetrievalHit`
  - `GraphContext`
  - `Citation`
  - `RetrievalTrace`
- 6.3. Implement Phase 6a endpoints:
  - `GET /health`
  - `POST /search`
- 6.4. Implement Phase 6b endpoints:
  - `POST /answer`
  - `GET /documents/{doc_id}/graph`
  - `GET /documents/{doc_id}/version-chain`
- 6.5. Add CORS config cho FE.
- 6.6. Add structured error response:
  - invalid request
  - ES unavailable
  - Neo4j unavailable
  - LLM unavailable
  - rerank timeout.
- 6.7. Add latency logging:
  - dense latency
  - sparse latency
  - fusion latency
  - rerank latency
  - graph latency
  - LLM latency.
- 6.8. Add lightweight cache:
  - graph neighbor cache.
  - optional search cache by normalized query and config.

Files to Create or Modify:

- `src/backend/app/main.py`
- `src/backend/app/config.py`
- `src/backend/app/schemas.py`
- `src/backend/app/dependencies.py`
- `src/backend/app/routes/search.py`
- `src/backend/app/routes/documents.py`
- `src/backend/app/routes/health.py`
- `tests/test_api_contract.py`

Deliverables and Outputs:

- Running FastAPI server.
- Swagger UI.
- API contract examples.
- Tests for request validation and response shape.

Acceptance Criteria:

- `/health` reports ES, Neo4j and LLM config status.
- `/search` returns results without LLM.
- Phase 6a is accepted when `/health`, `/search`, request validation and CORS work with mocked services.
- `/answer` returns answer, citations, retrieval trace and optional graph context.
- `/documents/{doc_id}/graph` returns graph nodes and edges.
- `/documents/{doc_id}/version-chain` returns chain.
- Phase 6b is accepted when `/answer` and graph endpoints work with real or mocked RetrievalService, GraphRetriever and AnswerService.
- Backend never exposes raw stack trace to FE.

Exit Criteria:

- After Phase 6a, FE can start integrating search without reading backend internals.
- After Phase 6b, demo can run from API alone using curl or Swagger.

Owner Suggestion:

- Backend API engineer.

Risks:

- If service dependencies are tightly coupled to pipeline scripts, app startup may become fragile. Use adapters and dependency injection.

### Phase 7: Frontend Contract Handoff

Goal:

Soạn contract đủ rõ để thành viên FE build UI độc lập, không phụ thuộc backend internals.

Inputs and Dependencies:

- Phase 6 API schemas.
- Mock responses nếu backend chưa xong.

Tasks:

- Viết `src/frontend/API_CONTRACT.md`.
- Cung cấp JSON examples cho:
  - `/health`
  - `/search`
  - `/answer`
  - `/documents/{doc_id}/graph`
  - `/documents/{doc_id}/version-chain`
- Định nghĩa FE controls:
  - Retrieval mode segmented control: Dense, Sparse, Hybrid.
  - Rerank toggle.
  - Rerank config panel: model, candidate_k, batch_size, device, timeout.
  - Temperature slider: 0.0 đến 1.0, default 0.2.
  - Filters: effect status, legal type, legal sector, issuing authority.
  - Graph toggle: enabled, use_lightrag, max_hops.
- Định nghĩa UI states:
  - loading
  - empty results
  - backend error
  - partial fallback
  - graph unavailable.
- Định nghĩa display rules:
  - citation list.
  - source chunks.
  - graph evidence.
  - retrieval trace debug panel.
- Ghi rõ FE không gọi ES, Neo4j, reranker hoặc LLM trực tiếp.

Files to Create or Modify:

- `src/frontend/API_CONTRACT.md`
- `src/frontend/README.md`
- Optional mock JSON files dưới `src/frontend/mocks/`.

Deliverables and Outputs:

- Frontend handoff spec.
- Mock payloads để FE làm việc trước khi backend hoàn chỉnh.

Acceptance Criteria:

- FE có thể build màn hình chính chỉ từ contract.
- Contract ghi rõ enum, default value và error shape.
- Contract không chứa chi tiết internal như Cypher query hoặc ES DSL.

Exit Criteria:

- FE member có thể tạo issue và implement UI không cần chờ hỏi lại backend về schema cơ bản.

Owner Suggestion:

- Backend API engineer phối hợp FE engineer.

Risks:

- Nếu backend response shape thay đổi sau khi FE bắt đầu, cần version hoặc update contract ngay.

### Phase 8: Evaluation and Error Analysis

Goal:

Đánh giá retrieval và KG bằng metrics đủ thuyết phục cho demo, đồng thời chỉ ra giới hạn hiện tại.

Inputs and Dependencies:

- Existing `output/eval_questions_gold.jsonl`.
- Existing retrieval outputs trong `output/`.
- Phase 1 KG artifacts.
- Phase 3 RetrievalService.
- Phase 4 GraphRetriever.

Tasks:

- Chuẩn hóa evaluation dataset:
  - query text
  - gold doc_id
  - gold chunk_id nếu có
  - query type
  - expected relation nếu là graph query.
- Tạo graph-specific evaluation set:
  - sửa đổi, bổ sung.
  - bãi bỏ, hết hiệu lực.
  - căn cứ, dẫn chiếu.
  - hướng dẫn, quy định chi tiết.
  - query có số hiệu văn bản.
- Chạy các cấu hình:
  - Dense
  - Dense + Rerank
  - Sparse
  - Sparse + Rerank
  - Hybrid
  - Hybrid + Rerank
  - Hybrid + Rerank + Graph expansion.
- Tính metrics:
  - Hit@3
  - Hit@5
  - Hit@10
  - MRR@10
  - nDCG@10
  - Recall@10
  - latency p50 và p95.
- Tính KG metrics:
  - link precision
  - link recall
  - direction accuracy
  - chain contains latest
  - article recall@10.
- Lấy mẫu semantic check:
  - 50 `AMENDS`
  - 50 `CITES`
  - 30 `REPEALS`
  - 30 `GUIDELINES`.
- Viết error analysis:
  - lỗi chunking.
  - lỗi metadata.
  - lỗi relation normalization.
  - lỗi sparse hoặc dense retrieval.
  - lỗi rerank.
  - lỗi answer synthesis.

Files to Create or Modify:

- `pipeline/07_evaluation/run_pipeline_eval.py`
- `pipeline/07_evaluation/evaluate_graph.py`
- `pipeline/07_evaluation/error_analysis.py`
- `output/report_artifacts/retrieval_metrics.csv`
- `output/report_artifacts/kg_metrics.csv`
- `output/report_artifacts/error_analysis.md`

Deliverables and Outputs:

- Metrics table cho retrieval modes.
- KG quality table.
- Error analysis report.
- 5 đến 10 query demo đã được kiểm chứng.

Acceptance Criteria:

- Có bảng so sánh 6 execution modes.
- Có ít nhất một nhóm query graph-specific cho thấy KG giúp trả đúng relation hoặc document update.
- Có báo cáo trung thực nếu KG không cải thiện global retrieval metrics.
- Có latency breakdown cho search và answer.

Exit Criteria:

- Nhóm có số liệu để giải thích với giảng viên vì sao dùng Hybrid, Rerank và KG.

Owner Suggestion:

- Evaluation engineer và Backend engineer.

Risks:

- Dataset gold nhỏ có thể làm metrics dao động mạnh. Cần ghi rõ sample size.

### Phase 9: Demo Script and Final QA

Goal:

Chuẩn bị kịch bản demo end-to-end theo khả năng người dùng, không chỉ theo thành phần kỹ thuật.

Inputs and Dependencies:

- Phase 6 API.
- Phase 7 FE hoặc Swagger fallback.
- Phase 8 evaluation results.
- Phase 10 deployment hoặc local stack.

Tasks:

- Chọn 5 đến 10 câu hỏi demo:
  - query thường.
  - query cần filter còn hiệu lực.
  - query so sánh dense, sparse, hybrid.
  - query bật/tắt rerank.
  - query có số hiệu văn bản.
  - query hỏi sửa đổi hoặc bãi bỏ.
  - query hỏi dẫn chiếu hoặc căn cứ.
- Chuẩn bị expected behavior cho từng query:
  - expected answer outline.
  - expected citations.
  - expected graph evidence.
  - expected retrieval trace.
- Chạy full demo rehearsal.
- Ghi checklist fallback:
  - Nếu FE lỗi, dùng Swagger.
  - Nếu LLM provider lỗi, show `/search` và graph endpoints.
  - Nếu full graph chậm, dùng subset demo graph.
  - Nếu reranker chậm, tắt rerank và giải thích tradeoff.

Files to Create or Modify:

- `docs/demo_script.md`
- `docs/demo_checklist.md`
- `output/report_artifacts/demo_queries.json`

Deliverables and Outputs:

- Demo script.
- QA checklist.
- Fallback plan.
- Final demo query set.

Acceptance Criteria:

- Có thể demo luồng query -> retrieval -> graph expansion -> answer -> citation.
- Có thể đổi Dense, Sparse, Hybrid và bật/tắt rerank trong FE.
- Có thể chỉnh temperature và trace ghi nhận đúng.
- Có thể show graph context cho ít nhất một văn bản.
- Có thể giải thích KG quality bằng metrics hoặc audit report.

Exit Criteria:

- Demo chạy ổn định trong một phiên rehearsal.
- Nhóm biết fallback nếu một dependency bên ngoài lỗi.

Owner Suggestion:

- Backend lead, FE lead và presenter.

Risks:

- Demo phụ thuộc LLM provider có thể bị rate limit. Cần chuẩn bị cached hoặc recorded examples nếu cần.

### Phase 10: Infrastructure and Deployment

Goal:

Package the FastAPI API as a Docker demo runtime that connects to external managed services: Elasticsearch Cloud, a dedicated Neo4j VPS and Google Cloud Vision OCR. Prioritize a reproducible demo over production automation.

Inputs and Dependencies:

- Phase 6 FastAPI app.
- Phase 2 Neo4j import path.
- Elasticsearch Cloud dense and sparse indexes.
- Neo4j VPS with the MVP graph imported.
- Google Service Account JSON credential for Vision OCR.
- FE app or placeholder.

Tasks:

- Create a Dockerfile for the API.
- Create a dedicated backend runtime requirements file. Do not install the root pipeline `requirements.txt` in the API image.
- Create Docker Compose demo config with:
  - `api`
  - optional `frontend`.
- Configure external services through env:
  - Elasticsearch Cloud URL, API key and index names.
  - Neo4j VPS Bolt URI, user, password and database.
  - Google Vision credential path.
  - LLM provider/API key.
  - Reranker provider/model while remaining provider-neutral for Jina AI or Voyage AI.
- Mount Google Service Account credential read-only into the API container for local demo runs.
- Add healthchecks:
  - API `/health`.
  - External ES/Neo4j/OCR checks only through backend health/degraded status if implemented.
- Add startup docs:
  - API container local mode.
  - Elasticsearch Cloud connection mode.
  - Neo4j VPS connection mode.
  - Google Vision OCR credential setup.
  - subset graph mode.
- If FE is public:
  - deploy FE to Vercel or Netlify.
  - configure backend base URL.
  - configure CORS.
- If backend is public:
  - run the API container on a prepared server or VPS.
  - configure reverse proxy and HTTPS if there is enough time.

Files to Create or Modify:

- `src/backend/Dockerfile`
- `src/backend/requirements.txt`
- `src/infra/docker-compose.yml`
- `src/infra/.env.example`
- `src/infra/README.md`
- `src/infra/scripts/`

Deliverables and Outputs:

- One clear command to run the API demo container.
- API container healthcheck.
- Deployment notes for demo with external Elasticsearch Cloud, Neo4j VPS and Google Vision.

Acceptance Criteria:

- API starts with Docker.
- `/health` returns OK or degraded clearly.
- Elasticsearch Cloud, Neo4j VPS and Google Vision credential are configured through env.
- Docker Compose does not start local Elasticsearch or local Neo4j in the default MVP demo path.
- There are clear instructions to run the API demo container and configure external services.

Exit Criteria:

- Presenter can run the API demo on a prepared machine or server and connect to Elasticsearch Cloud and the Neo4j VPS.

Owner Suggestion:

- Infra lead and Backend engineer.

Risks:

- The Neo4j VPS has limited RAM, so MVP graph traversal remains one-hop and should use a subset graph if needed.
- Google Service Account JSON is a sensitive credential and must not be committed to git.

## 9. Task Prioritization

| Priority | Task | Phase | Keep, Modify, Drop | Notes |
| --- | --- | --- | --- | --- |
| P0 | Scope freeze, env, README MVP | 0 | Add | Chặn hiểu nhầm Qdrant và Neo4j Free |
| P0 | Relationship Graph Cleaning | 1 | Keep, mostly done | Cần audit artifact sau code change |
| P0 | Preserve `raw_label` | 1 | Keep, done in code | Cần verify CSV và Neo4j import |
| P0 | KG rebuild | 1 | Keep | Bắt buộc trước app |
| P0 | Neo4j import | 2 | Keep | Có subset và full path |
| P0 | Dense/Sparse ES service | 3 | Keep | ES-only runtime |
| P0 | Hybrid RRF | 3 | Keep | Reuse evaluation code nếu được |
| P0 | Rerank toggle | 3 | Keep | 6 execution modes |
| P0 | Metadata filtering | 3 | Keep | Áp cho dense và sparse |
| P0 | FastAPI `/search` | 6a | Add | FE cần sớm, không phụ thuộc LightRAG |
| P0 | FastAPI `/answer` | 6b | Add | Demo chính, phụ thuộc LightRAG và AnswerService |
| P1 | GraphRetriever | 4 | Keep | Needed for KG demo |
| P1 | LightRAG orchestration | 5 | Keep, narrowed | Runtime orchestration, không thay ingestion |
| P1 | Version chain queries | 4 | Keep | Demo legal update |
| P1 | Citation queries | 4 | Keep | Demo legal basis |
| P1 | FE API contract | 7 | Add | FE handoff |
| P1 | Evaluation dataset | 8 | Keep | Add graph-specific cases |
| P1 | KG metrics | 8 | Add | Link precision, recall, direction |
| P1 | Error analysis | 8 | Keep | Cần cho báo cáo |
| P1 | Docker Compose demo | 10 | Keep, simplified | Không production CI/CD |
| P3 | Cache and latency optimization | Future | Defer | Cache la future enhancement, khong schedule truoc khi hoan tat MVP hien tai |
| P2 | Public FE deploy | 10 | Optional | Chỉ nếu backend public ổn |
| P3 | CI/CD and monitoring | 10 | Defer | Basic test workflow nếu còn thời gian |
| P3 | Incremental updates | Future | Defer | Ghi future work |
| P3 | Production deployment | Future | Defer | Không cần cho demo lớp |
| P3 | Stress test 100 request/s | Future | Drop from MVP | Không phù hợp scope |

## 10. Definition of Demo Done

MVP được xem là đủ demo khi người dùng có thể thực hiện các khả năng sau:

- Nhập câu hỏi pháp luật và nhận answer có citation.
- Chọn Dense, Sparse hoặc Hybrid trên FE.
- Bật hoặc tắt rerank và thấy execution mode tương ứng trong trace.
- Chỉnh temperature và backend truyền đúng giá trị vào LLM.
- Bật filter còn hiệu lực và kết quả không trả văn bản hết hiệu lực nếu metadata cho phép.
- Hỏi câu có số hiệu văn bản và hệ thống ưu tiên document đúng.
- Hỏi câu về sửa đổi, bãi bỏ, dẫn chiếu hoặc hướng dẫn và hệ thống trả graph evidence.
- Xem document graph 1-hop cho một văn bản.
- Xem version chain hoặc citation chain cho một văn bản mẫu.
- Xem retrieval trace để giải thích câu trả lời đến từ Dense, Sparse, Hybrid, Rerank hay KG.
- Xem bảng evaluation so sánh Dense, Sparse, Hybrid, có và không có Rerank.
- Xem KG quality report gồm structural checks và sampled semantic checks.
- Chạy demo bằng Docker Compose, Swagger hoặc FE với fallback rõ ràng nếu một service lỗi.

## 11. KG Evaluation Criteria

### Structural Checks

Các checks chạy trên artifact trước import và sau import Neo4j:

- `missing_endpoint_edges = 0` trong importable document relationships.
- `self_loop_edges = 0` trong importable document relationships.
- `duplicate_document_ids = 0`.
- `duplicate_article_or_chunk_ids = 0`.
- `unknown_canonical_relation_count = 0`.
- `document_relationship_edges_with_raw_label_ratio = 100%`.
- `HAS_CHUNK` hoặc `HAS_ARTICLE` count bằng số chunk/article importable.
- Edge type distribution được ghi lại để phát hiện lệch bất thường.

### Semantic Checks

Lấy mẫu thủ công và xác minh:

- 50 edge `AMENDS`.
- 50 edge `CITES`.
- 30 edge `REPEALS`.
- 30 edge `GUIDELINES`.

Với mỗi edge, kiểm tra:

- source document đúng.
- target document đúng.
- canonical type đúng.
- hướng cạnh đúng.
- `raw_label` phản ánh nhãn gốc.

Target chất lượng MVP, không phải hard blocker tuyệt đối cho demo nếu report giải thích rõ nguyên nhân và giới hạn:

- Edge type precision `AMENDS`, `CITES`, `GUIDELINES` >= 90%.
- Edge type precision `REPEALS` >= 80%.
- Direction accuracy >= 95%.

### Graph Query Checks

Tạo 20 đến 30 gold cases:

- Document A được sửa đổi bởi văn bản nào.
- Document A sửa đổi văn bản nào.
- Document A dẫn chiếu văn bản nào.
- Document A được hướng dẫn bởi văn bản nào.
- Document A có Article hoặc Chunk nào liên quan.

Metrics:

- `link_precision`.
- `link_recall`.
- `chain_contains_latest`.
- `chain_exact_match` nếu có gold chain đầy đủ.
- `article_recall@10`.

### Retrieval Contribution Checks

So sánh:

- Dense.
- Dense + Rerank.
- Sparse.
- Sparse + Rerank.
- Hybrid.
- Hybrid + Rerank.
- Hybrid + Rerank + Graph expansion.

Metrics:

- Hit@3.
- Hit@5.
- Hit@10.
- MRR@10.
- nDCG@10.
- Recall@10.
- Latency p50.
- Latency p95.

Kỳ vọng thực tế:

- KG không bắt buộc cải thiện mọi query.
- KG phải cải thiện hoặc giải thích tốt hơn nhóm query có số hiệu văn bản, sửa đổi, bãi bỏ, dẫn chiếu, hướng dẫn.

## 12. Immediate Next Steps

Thứ tự thực thi đề xuất:

1. Phase 0: chốt scope, env và README MVP.
2. Phase 1: rebuild và audit KG artifacts.
3. Phase 3: consolidate retrieval service song song với Phase 1.
4. Phase 2: import Neo4j subset và verify graph.
5. Phase 4: implement GraphRetriever.
6. Phase 6: dựng FastAPI `/search` sớm, sau đó `/answer`.
7. Phase 5: hoàn thiện LightRAG orchestration cho `/answer`.
8. Phase 7: handoff FE contract ngay khi API schema ổn định.
9. Phase 8: chạy evaluation và error analysis.
10. Phase 10: đóng gói Docker Compose.
11. Phase 9: rehearsal và final QA.

Nếu thời gian hạn chế, ưu tiên demo path tối thiểu:

1. Hybrid + Rerank search.
2. Neo4j subset graph.
3. GraphRetriever cho document number và 1-hop relations.
4. `/answer` có citation và trace.
5. FE hoặc Swagger hiển thị được output.
