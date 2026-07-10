# Task List — Search, OCR, Graph Integration

Status: DRAFT — awaiting approval. No task starts until sign-off.
Legend: 🔑 = requires external credentials or live services (skip-guarded in CI). Phases per `-plan.md`; findings per `-audit.md`.
Verify command baseline for every task: `python -m pytest tests` (green without live credentials).

---

## A. Backend — hardening (Phase 0–1)

| ID | Task | Files | Tests | Verify |
|----|------|-------|-------|--------|
| A1 | Add bounds + rerank-model allowlist to request schema (`top_k≤50`, `top_k≤candidate_k≤200`, `max_hops≤2`, `timeout_ms≤120000`) | `src/backend/app/schemas.py` | new `tests/test_request_validation.py`: 422 on `top_k=1000`, off-allowlist model, `candidate_k<top_k` | `python -m pytest tests/test_request_validation.py` |
| A2 | Mirror bounds in dataclasses; align `RerankConfig.model` default to `rerank-2.5` (B8) | `src/backend/services/retrieval_modes.py` | extend A1 file: dataclass `ValueError` cases, default equality schema↔dataclass | same |
| A3 | Safe `_getenv_int`/`_getenv_bool` (B9): malformed → default + warning | `src/backend/app/config.py` | new cases in `tests/test_backend_runtime_integration.py` | `python -m pytest tests/test_backend_runtime_integration.py` |
| A4 | Global exception handler; structured `{"error","detail","warnings"}`; sanitize exception class names out of warnings (B2, I1) | `src/backend/app/main.py`, `dependencies.py` | new `tests/test_error_handling.py`: forced retriever raise → 502 shape, no traceback/class name in body | `python -m pytest tests/test_error_handling.py` |
| A5 | Health degraded-logic fix (B12): `extractive`/`noop` degrade only when a higher provider was configured | `src/backend/app/routes/health.py` | health matrix cases in `test_backend_runtime_integration.py` | pytest file |
| A6 | Lifespan runtime state replacing `@lru_cache`; live probes (ES ping, Neo4j verify) with 30 s cache; fallback re-init path (B4, B10) | `src/backend/app/dependencies.py`, `main.py`, `routes/health.py` | rework reload helper in `test_backend_runtime_integration.py`; probe-cache + degraded-flip tests with mocked clients | pytest file |
| A7 | Enforce `llm.max_context_chunks`; Voyage timeout enforcement, timeout → original order + `rerank.timeout` warning (B5) | `src/backend/services/lightrag_service.py`, `rerank_service.py` | new `tests/test_rerank_service.py`, context-cap case in lightrag tests | `python -m pytest tests/test_rerank_service.py` |
| A8 | Missing unit tests backfill: `FusionRetriever.merge`, `build_filter_clauses` (ranges, doc_id list), `ContextAssembler` dedupe, `IntentDetector` | none (tests only) | new `tests/test_retrieval_units.py` | `python -m pytest tests/test_retrieval_units.py` |
| A9 | Prune deps (`google-cloud-compute`, `boto3` — grep infra first); add `.dockerignore` | `src/backend/requirements.txt`, `.dockerignore` | build smoke: `docker build -f src/backend/Dockerfile .` (local only) | grep + docker build 🔑(docker only) |

## B. Search — dense + hybrid (Phase 2)

| ID | Task | Files | Tests | Verify |
|----|------|-------|-------|--------|
| B1 | local HF `EMBEDDING_MODEL/DEVICE/CACHE_DIR/MAX_LENGTH/DIMS` settings | `src/backend/app/config.py` | settings-read cases | pytest |
| B2 | `embedding_service.py`: local Hugging Face `darklethelong/vnlegal-lal` query embedder (Protocol; no external embedding API) | new `src/backend/services/embedding_service.py` | new `tests/test_embedding_service.py` (mocked encoder) | pytest |
| B3 | `ElasticsearchDenseRetriever` (knn query, shared filters/mapper, `scores={"dense":…}`) | `src/backend/services/elasticsearch_retriever.py` | knn-body assertions with `Mock()` client in `tests/test_dense_retrieval.py` | pytest |
| B4 | Wire dense in DI; remove permanent `dense_vector_query_unavailable`; sparse-alias + warning when unconfigured; hybrid single-pass when aliased (B1-audit) | `src/backend/app/dependencies.py`, `retrieval_service.py` | trace asserts: hybrid = 1 BM25 + 1 kNN when configured; 1 BM25 when not | pytest |
| B5 | Startup vector-dim check vs alias mapping; mismatch → dense disabled + warning | `dependencies.py` | mocked `indices.get_mapping` cases | pytest |
| B6 🔑 | Live smoke: dense + hybrid against ES Cloud staging index; confirm pipeline embedding model/dims (see `pipeline/03_embeddings`) | none | manual | `curl -s localhost:8000/search -d '{"query":"...","retrieval_mode":"dense",...}'` - requires `ELASTICSEARCH_URL/API_KEY` and local HF model cache |
| B7 🔑 | Decision gate: if index `vector` mapping unusable for kNN → STOP, write reindex proposal (separate approval; production data) | docs only | — | — |

## C. Graph (Phase 3)

| ID | Task | Files | Tests | Verify |
|----|------|-------|-------|--------|
| C1 | Honor `max_hops`; intent/document-number seed selection | `src/backend/services/graph_retriever.py` | mocked-driver Cypher assertions in new `tests/test_graph_retriever.py` | pytest |
| C2 | Populate `related_chunks` via injected chunk-fetcher (ES top-1 per ≤3 neighbor docs, intent-prioritized relations) | `graph_retriever.py`, `dependencies.py` | fetcher-injection tests; assembler dedupe interplay | pytest |
| C3 | Trace additions (`graph_chunks_used`, latency segments); context-cap ordering retrieval→graph | `lightrag_service.py` | extend lightrag tests | pytest |
| C4 | Implement `GET /documents/{doc_id}/version-chain` (AMENDS/REPEALS ordered walk) (B11) | `routes/documents.py`, `graph_retriever.py` | route test with mocked driver | pytest |
| C5 🔑 | Live smoke against droplet Neo4j (graph shape per `tests/test_neo4j_verification.py`) | none | manual | `curl /documents/<id>/version-chain` — requires `NEO4J_*` |

## D. OCR (Phase 4)

| ID | Task | Files | Tests | Verify |
|----|------|-------|-------|--------|
| D1 | Refactor OCR service: no import-time `load_dotenv`; credentials via `Settings`; lazy client (B7) | `src/backend/services/ocr_service.py`, `config.py` | construction tests (env present/absent) in new `tests/test_ocr_endpoint.py` | pytest |
| D2 | `POST /documents/ocr`: multipart, `OCR_MAX_FILE_MB` cap, mime allowlist, PDF ≤5-page pre-check (add `pypdf`), error mapping 413/415/422/503 | new `src/backend/app/routes/ocr.py`, `main.py`, `requirements.txt` | mocked-Vision happy path + all error paths | `python -m pytest tests/test_ocr_endpoint.py` |
| D3 | `/health` reports `ocr` status | `dependencies.py`, `routes/health.py` | health case | pytest |
| D4 🔑 | Live Vision smoke (1 image, 1 small PDF) — Google credentials + billing; skip-guarded | none | `@pytest.mark.skipif` live test | requires `GOOGLE_SERVICE_ACCOUNT_*` or `GOOGLE_APPLICATION_CREDENTIALS` |

## E. Frontend (Phase 5)

| ID | Task | Files | Tests | Verify |
|----|------|-------|-------|--------|
| E1 | Set `window.AURORA_API_BASE` in pages; localhost dev fallback (F1) | `src/frontend/chat.html`, `index.html` | extend `tests/test_frontend_backend_connection.py` | pytest |
| E2 | `AbortController` 30 s timeout; distinct timeout/error copy (F3) | `src/frontend/app.js` | static assertions | pytest |
| E3 | Label handoff as demo (F2) | `app.js`, `chat.html` | static assertion: demo label present | pytest |
| E4 | OCR upload control → `/api/documents/ocr`, `textContent`-only rendering (after D2) | `app.js`, `chat.html`, `styles.css` | static assertions | pytest + manual browser check |
| E5 | Slim frontend image (no `AURORA.md`/Dockerfile in web root); nginx gzip/cache/nosniff (F5) | `src/frontend/Dockerfile`, `nginx.conf` | `tests/test_infra_deployment_config.py` additions | pytest |

## F. Infrastructure & CI (Phase 6)

| ID | Task | Files | Tests | Verify |
|----|------|-------|-------|--------|
| F1 | Regenerate all three env examples from `config.py`; remove dead vars (`ELASTICSEARCH_DENSE_INDEX/SPARSE_INDEX`, `DEFAULT_RETRIEVAL_MODE`, `DEFAULT_TEMPERATURE`) or wire them; section backend vs infra (S1) | `.env.example`, `src/infra/.env.example`, `src/infra/production.env.example` | update `tests/test_infra_deployment_config.py`; new test: example keys ⊇ `Settings` env reads | pytest |
| F2 | Bind backend `127.0.0.1:8000` in production compose; pass `EMBEDDING_*`/OCR vars (S3) | `src/infra/docker-compose.production.yml` | infra config tests | pytest |
| F3 | nginx `limit_req` on `/api/`; optional `API_SHARED_SECRET` header + backend check (I2) | `src/frontend/nginx.conf`, backend middleware | middleware test | pytest |
| F4 | CI: add `ruff check`; guard "no tracked non-example `*.env`"; audit live-service tests for skip guards (S6) | `.github/workflows/ci.yml`, test files | CI run itself | push to branch, CI green |
| F5 🔑 | CD post-deploy health gate (`curl /health` retry loop) (S5) — **touches production deploy path; separate review** | `.github/workflows/deploy.yml` | staged deploy | requires droplet secrets |
| F6 | One-time git-history scan for past `*.env` commits (S2); rotate if found | none | — | `git log --all --diff-filter=A -- "*.env"` |

## G. Documentation (Phase 7)

| ID | Task | Files | Verify |
|----|------|-------|--------|
| G1 | API reference (endpoints, error codes, limits, failure matrix) | `src/README.md` or `docs/` | review |
| G2 | Env variable matrix + "dense model must match index-time model" warning | `src/infra/README.md`, root `README.md` | review |
| G3 | Decision log (dense provider, reindex deferral, OCR sync-only limit) | `docs/roadmap/` | review |

---

## Dependency graph (coarse)

```
A1–A9 ──► B1–B5 ──► B6🔑 ──► B7 gate
   └────► C1–C4 ──► C5🔑
   └────► D1–D3 ──► D4🔑 ──► E4
E1–E3, E5 independent after A-block
F1–F2 after B/C/D env vars final; F4 anytime; F5🔑 last
```

## Explicitly requires external credentials / live services

`B6, B7, C5, D4, F5` — everything else runs fully mocked in CI. Production-touching items (`B7` reindex, `F5` deploy) each need their own approval before execution.
