# Next Phase Specification — Search, OCR, Graph Integration

Status: DRAFT — awaiting approval. No implementation until sign-off.
Companion docs: `next-phase-search-ocr-graph-integration-audit.md` (findings referenced as B1/F2/S1/…), `-plan.md`, `-tasks.md`.

---

## 1. Problem statement

The MVP backend serves BM25-only retrieval while advertising dense/hybrid modes (B1), graph context never reaches answers (B6), OCR exists as dead code with no API surface (B7), and request limits/error handling are missing (B2, B3). The next phase makes the advertised architecture real: true hybrid search, an OCR ingestion endpoint, graph-augmented answers, and hardened contracts — without breaking the existing frontend `/answer` contract.

## 2. Goals

1. Real dense retrieval (query-time embedding + ES kNN) and honest hybrid RRF fusion.
2. Graph context that contributes `related_chunks` to answers; working `version-chain`; `max_hops` honored.
3. OCR upload endpoint wrapping `GoogleVisionOcrService` (images + PDFs ≤5 pages sync; larger PDFs rejected with a clear error in this phase).
4. Reranking hardened: enforced timeout, server-side model allowlist, bounded candidate sets.
5. Truthful `/health` (live dependency probes) and structured error responses.
6. Env/config reconciliation across the three example files (S1).
7. Frontend: configurable API base, request timeout, honest handoff labeling (F1–F3).

## 3. Non-goals

- No re-chunking or re-embedding of the corpus (pipeline outputs are inputs, not targets).
- No auth system (only a minimal shared-secret/rate-limit stopgap at nginx; full auth is a later phase).
- No real attorney-handoff backend (label as demo only).
- No async/GCS OCR for >5-page PDFs (documented limitation).
- No LightRAG library adoption; "graph-augmented retrieval" stays custom.
- No streaming answers.

## 4. User-facing workflows

1. **Ask a legal question** (existing): chat → `POST /api/answer` → answer + citations + trace. Unchanged contract; graph-sourced context now appears in `citations` with `source: "graph"` available in `retrieval_context`… (additive fields only).
2. **Upload a scanned document**: chat page gains an upload control → `POST /api/documents/ocr` → extracted text preview returned; user can then ask questions quoting it (client-side only; no indexing this phase).
3. **Explore document relations**: existing `GET /api/documents/{doc_id}/graph`; new working `GET /api/documents/{doc_id}/version-chain` (AMENDS/REPEALS chain ordered by issue date).

## 5. API contracts

All changes are **additive**; existing fields keep shape.

### 5.1 `POST /search`, `POST /answer` (request)

- `top_k`: add bound `1 ≤ top_k ≤ 50`.
- `rerank.candidate_k`: `top_k ≤ candidate_k ≤ 200`.
- `rerank.model`: must be in server allowlist (`rerank-2.5`, `rerank-2.5-lite`); else 422.
- `graph.max_hops`: `0 ≤ max_hops ≤ 2`.
- `retrieval_mode`: `dense` requires embedding provider configured; else 409 `{"error": "dense_unavailable", "fallback": "sparse"}` — or silent sparse fallback + warning when `RUNTIME_FALLBACK_ENABLED=true`.

### 5.2 `POST /answer` (response, additive)

```json
{
  "answer": "...", "citations": [...],
  "retrieval_context": [...],
  "graph_context": { "center": ..., "nodes": [...], "edges": [...], "related_chunks": [...], "query_intent": "..." },
  "retrieval_trace": { ..., "dense_used": true, "graph_chunks_used": 2, "rerank_ms": 123, "retrieval_ms": 88 },
  "warnings": [...], "latency_ms": 456
}
```

### 5.3 `POST /documents/ocr` (new)

- Multipart: `file` (image/* or application/pdf), max 10 MB (413 otherwise).
- 200: `{"success": true, "text": "...", "pages": [{"page_num": 1, "text": "..."}], "mime_type": "..."}` (existing service shape).
- 415 unsupported type; 422 PDF >5 pages: `{"error": "pdf_too_large_for_sync_ocr", "max_pages": 5}`; 503 Vision not configured: `{"error": "ocr_not_configured"}`.

### 5.4 `GET /documents/{doc_id}/version-chain` (implemented)

`{"doc_id": "...", "chain": [{"doc_id": ..., "document_number": ..., "relation": "AMENDS|REPEALS", "direction": "in|out", "title": ...}]}`

### 5.5 Errors (all endpoints)

Global handler → `{"error": <code>, "detail": <safe message>, "warnings": [...]}`; 502 for upstream (ES/Neo4j/LLM/Voyage) failures, 422 validation, never raw tracebacks. Exception class names removed from client-visible warnings (I1).

## 6. Search and retrieval behavior

- **Sparse**: current BM25 multi_match, unchanged fields/boosts.
- **Dense**: query-time embedding via configured provider (`EMBEDDING_PROVIDER`: `voyage` | `openai-compatible` | `none`); ES `knn` query against the `vector` field of `vietlegal_chunks_hybrid_v1` (`k=candidate_k`, `num_candidates=4*candidate_k`, same filter clauses). Embedding model **must match** the pipeline model used at index time — recorded in index metadata; startup check compares dims and warns on mismatch.
- **Hybrid**: dense + sparse each retrieve `candidate_k`, existing `FusionRetriever` RRF (k=60) merges to `candidate_k`, then rerank/truncate to `top_k`. When dense is unavailable: behave per §5.1.
- Filters: unchanged (`term`/`terms`/`ranges`, `.keyword` for exact fields).

## 7. OCR behavior

- Route wraps `GoogleVisionOcrService`; service becomes lazily constructed (no import-time `load_dotenv`; settings flow through `config.py`).
- Sync only; PDF page count checked before Vision call (pypdf or content heuristic) to fail fast at 5-page limit.
- No storage: response only; nothing indexed, nothing persisted (privacy-preserving default).
- Status surfaced in `/health` as `ocr: configured|disabled`.

## 8. Reranking behavior

- Voyage call wrapped with `timeout_ms` enforcement (thread + timeout or SDK timeout param); on timeout → original order + `warnings: ["rerank.timeout"]`.
- Model from allowlist only; `batch_size` documented as unused (Voyage API takes full list) and removed from the request schema **later** — kept accepted-but-ignored this phase for frontend compat.
- `NoopReranker` unchanged as fallback.

## 9. Graph behavior

- `GraphRetriever.retrieve`: seed doc selection upgraded — use `IntentDetector.document_number` match against hits first, else top-hit `doc_id` (current behavior).
- Honor `max_hops` (1 or 2) via variable-length Cypher with relation filter, `LIMIT 100` retained.
- **Populate `related_chunks`**: for up to N=3 neighbor docs (prioritized by intent-matching relation: amendment→AMENDS, repeal→REPEALS, guideline→GUIDELINES, citation→CITES), fetch top-1 chunk per doc from ES (`term: doc_id`, BM25 with original query) as `AnswerContext(source="graph", relation=..., raw_label=...)`. `ContextAssembler` dedupe already handles overlap.
- `version-chain`: Cypher walk over AMENDS/REPEALS ordered chain from the doc node.
- `max_context_chunks` enforced in `LightRAGService` before answer call (retrieval first, graph fills remainder).

## 10. Configuration and secrets

New env (names only; values never committed):

| Var | Default | Purpose |
|---|---|---|
| `EMBEDDING_PROVIDER` | `none` | dense query embeddings |
| `EMBEDDING_MODEL` | (provider-specific) | must match index-time model |
| `EMBEDDING_API_KEY` | — | provider key |
| `OCR_PROVIDER` | `google-vision` | future-proofing |
| `OCR_MAX_FILE_MB` | `10` | upload cap |
| `API_SHARED_SECRET` | — | optional nginx→backend header check |

Reconciliation (S1): single source of truth = `config.py` `Settings`; all three example files regenerated to match, sectioned `# backend-runtime` vs `# infra/pipeline-only`; remove dead `ELASTICSEARCH_DENSE_INDEX/SPARSE_INDEX`, `DEFAULT_RETRIEVAL_MODE`, `DEFAULT_TEMPERATURE` or wire them. `production.env` stays git-ignored; add a CI guard asserting no `*.env` (non-example) file is tracked.

## 11. Observability and failure modes

- Structured logging (stdlib `logging`, JSON-ish single line): request id, route, mode, latency segments (`retrieval_ms`, `rerank_ms`, `graph_ms`, `llm_ms`), warning codes.
- `/health` performs live probes with short timeouts (ES `ping`, Neo4j `verify_connectivity`, cached 30 s) — status becomes truthful (B2/B4); `degraded` recomputed; `llm=extractive` counts as degraded **only if** `LLM_PROVIDER` was set to something else (B12).
- Failure matrix: ES down → 502 (`/search`) or fallback per `RUNTIME_FALLBACK_ENABLED`; Neo4j down → answer proceeds, `warnings: ["graph.unavailable"]`; Voyage down/timeout → original order + warning; LLM down → extractive fallback + warning; Vision down → 503 on `/documents/ocr` only.

## 12. Acceptance criteria

1. `retrieval_mode=dense` issues an ES `knn` query (assert via mocked client) and `hybrid` issues one BM25 + one kNN, RRF-merged — no duplicate BM25 pair.
2. Requests with `top_k=1000` or off-allowlist rerank model return 422.
3. `/answer` on a doc with graph neighbors returns ≥1 `graph_context.related_chunks` and answer contexts include `source: "graph"` items; `max_context_chunks` respected.
4. `POST /documents/ocr` happy path (mocked Vision) returns page-structured text; 6-page PDF → 422; no credentials → 503; `/health` shows `ocr`.
5. `GET /documents/{id}/version-chain` returns ordered chain from mocked Neo4j.
6. ES outage after startup: `/health` flips to degraded within 60 s; `/search` returns structured 502 or fallback, never a raw 500 traceback.
7. All three env example files contain exactly the variables read by `config.py` + documented infra vars; CI guard passes.
8. Frontend: API base configurable via `window.AURORA_API_BASE` set in HTML (or meta tag), fetch aborts at 30 s with user-visible message; handoff bubble labeled as demo.
9. Full CI suite green without live credentials (all live-service tests skip cleanly, S6).
