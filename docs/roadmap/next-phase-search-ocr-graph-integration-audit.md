# Codebase Audit Report — VietLegalGraphRAG

Date: audit of working tree at HEAD (branch state per repo). Documentation only — no source changes made.
Scope: `src/` primary; `tests/`, infra, CI, env examples as supporting context. `data/`, `node_modules/`, build outputs not inspected. No secret values read or printed.

---

## 1. Current architecture summary

```
Browser (static HTML/JS, nginx)            src/frontend/
   └─ POST /api/answer ── nginx proxy ──► FastAPI backend        src/backend/app/
                                             ├─ RetrievalService (dense/sparse/hybrid + RRF + rerank)
                                             │    └─ ElasticsearchTextRetriever (BM25 multi_match only)
                                             ├─ GraphRetriever (Neo4j, 1-hop doc relations)
                                             ├─ VoyageReranker | NoopReranker
                                             ├─ ExtractiveAnswerService | OpenAICompatibleAnswerService
                                             └─ LightRAGService (orchestrator: retrieve → graph → assemble → answer)
Offline pipeline (EDA→preprocess→embeddings→graph→eval)          pipeline/01..05
Infra: docker-compose (backend + nginx frontend), Neo4j on separate droplet, ES Cloud external.
CI: pytest on push/PR (main, develop). CD: scp + docker compose on droplet.
```

Key runtime behavior: `dependencies.get_runtime_services()` builds all clients once (`@lru_cache`), degrades to demo/noop/extractive fallbacks when env is missing, and reports per-service status via `/health` and `retrieval_trace`.

## 2. Backend findings

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| B1 | **High** | "Dense" retrieval is not dense. `dense_retriever` and `sparse_retriever` are the **same** `ElasticsearchTextRetriever` (BM25). `hybrid` runs the identical query twice and RRF-merges two identical lists (score `2/(k+rank)`, order unchanged) — doubled ES load, misleading `execution_mode`, and the `dense_vector_query_unavailable` warning is permanent. | `src/backend/app/dependencies.py` (`_build_retrieval_service`), `src/backend/services/retrieval_service.py` |
| B2 | **High** | No error handling on request path. `Elasticsearch` client construction is lazy, so `status="configured"` even if unreachable; the first real failure surfaces as an unhandled 500 from `/search` / `/answer` (retrieval errors are not caught; only graph errors are). No global exception handler. | `routes/search.py`, `dependencies.py` |
| B3 | **High** | Unbounded request parameters: `top_k` and `rerank.candidate_k` are `gt=0` with **no upper bound** → a single request can demand `size=10^9` from ES and huge Voyage rerank batches (cost + DoS vector). Client also controls the Voyage `model` string per request. | `app/schemas.py`, `services/retrieval_service.py`, `services/rerank_service.py` |
| B4 | Medium | `@lru_cache` singleton pins the first-request outcome forever: if ES/Neo4j were down at first request, backend stays in fallback until process restart. `warnings`/`status` are also process-global. `/health` reflects construction-time state, never live connectivity. | `dependencies.py`, `routes/health.py` |
| B5 | Medium | `request.llm.max_context_chunks` is never enforced — all retrieved contexts go to the LLM prompt; `rerank.batch_size`, `device`, `timeout_ms` are accepted but ignored (no batching, no timeout on Voyage call). | `answer_service.py`, `rerank_service.py`, `lightrag_service.py` |
| B6 | Medium | `GraphRetriever.get_document_neighbors` ignores `depth`/`max_hops` (Cypher is fixed 1-hop, `LIMIT 100`; `depth=` is passed as an unused Cypher param). `GraphContext.related_chunks` is never populated, so graph context **never reaches the answer** — `ContextAssembler` graph-merge branch is dead code. "LightRAG" is a naming shell; no LightRAG algorithm/library involved. | `graph_retriever.py`, `context_assembler.py`, `lightrag_service.py` |
| B7 | Medium | OCR service (`GoogleVisionOcrService`) exists but is wired to **no route** — dead code at runtime, only usable via `__main__` CLI. Sync PDF path limited to 5 pages (documented in-code). `load_dotenv` runs at import time (side effect). | `services/ocr_service.py` |
| B8 | Medium | Default-config drift: `RerankConfig.model` defaults to `BAAI/bge-reranker-v2-m3` (dataclass) vs `rerank-2.5` (pydantic schema). Direct dataclass users get a model name Voyage cannot serve. | `retrieval_modes.py` vs `schemas.py` |
| B9 | Low | `_getenv_int` calls `int(value)` uncaught → malformed `ELASTICSEARCH_REQUEST_TIMEOUT` crashes startup with a raw `ValueError`. | `app/config.py` |
| B10 | Low | `_elasticsearch_is_configured` returns true when only auth vars are set → client points at default `http://localhost:9200` inside the container ("configured" but broken). | `dependencies.py` |
| B11 | Low | `/documents/{doc_id}/version-chain` is a stub returning `{"chain": []}` with no `501`/warning marker. | `routes/documents.py` |
| B12 | Low | Health semantics: `llm=extractive` marks status `degraded` even when extractive is the intended provider (`LLM_PROVIDER=extractive` default). Also `src/infra/.env.example` uses `LLM_PROVIDER=mock`, which silently maps to extractive. | `routes/health.py`, `config.py` |
| B13 | Low | Flat-module layout (`PYTHONPATH=/app/src/backend/services:/app/src/backend/app`, `from config import ...`) — generic top-level module names (`config`, `main`, `schemas`) risk collisions; tests must replicate sys.path games. No package (`src.backend.*`) imports. | `Dockerfile`, all modules, `tests/test_backend_runtime_integration.py` |
| B14 | Low | Dependency bloat in `src/backend/requirements.txt`: `google-cloud-compute` and `boto3` are imported nowhere in `src/`. Docker image runs as root; no `.dockerignore` for build context `../..` (whole repo, incl. `data/` if present, is sent to the docker build daemon). | `requirements.txt`, `src/backend/Dockerfile` |

## 3. Frontend findings

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| F1 | Medium | `window.AURORA_API_BASE` is never set by any page; base defaults to `/api`, which only works behind the nginx proxy. Opening the static site directly (dev) always hits the offline path. No dev fallback (e.g., `http://localhost:8000`). | `src/frontend/app.js`, `index.html`, `chat.html` |
| F2 | Medium | `requestHandoff()` **fakes** an attorney handoff ("Someone will pick up the full conversation history") with a `setTimeout`. No backend call exists. Misleading product claim — must be labeled demo or implemented. | `app.js` |
| F3 | Low | `fetch` has no timeout/AbortController — a hung backend leaves the typing indicator forever. No retry, generic error copy. | `app.js` |
| F4 | Low | XSS posture is good (answers/citations rendered via `textContent`), but raw backend error text is thrown into `Error` and only logged — fine. Keep `textContent` discipline for future fields (`trace`, graph). | `app.js` |
| F5 | Low | Frontend image copies **all** of `src/frontend/` into nginx web root — `AURORA.md` (58 KB design doc) and Dockerfile become publicly downloadable. nginx has no gzip, cache headers, or CSP. | `src/frontend/Dockerfile`, `nginx.conf` |

## 4. Integration findings

- **I1 (Medium):** `/search` and `/answer` responses embed `runtime.warnings` including exception class names (`elasticsearch.init_failed:<ExcName>`) — minor internal-detail leak to any caller.
- **I2 (Medium):** No auth or rate limiting on any endpoint while `/answer` can trigger paid Voyage + LLM calls — direct cost-abuse exposure once deployed publicly (`FRONTEND_PORT=80`, backend `8000` also published on the droplet host).
- **I3 (Low):** nginx proxies `/api/` (trailing slash) only; `/api` bare returns the SPA fallback. Consistent with frontend usage; document it.
- **I4 (Low):** `graph.enabled=false` vs `use_lightrag=false` are indistinguishable in behavior; trace reports both flags but the distinction is unimplemented.

## 5. External service findings

- **Elasticsearch:** hybrid index `vietlegal_chunks_hybrid_v1` + alias `vietlegal_chunks`; backend excludes `vector` from source (good) but never issues a kNN/dense query (B1). `filters.ranges` supported; `TEXT_EXACT_FIELDS` get `.keyword` suffix — assumes mapping has keyword subfields (unverified at runtime).
- **Neo4j:** relations `AMENDS/CITES/REPEALS/GUIDELINES`, undirected match with direction inferred from center. Driver connectivity never verified at build (`GraphDatabase.driver` is lazy) → `status=configured` may be false.
- **Voyage:** failure → log + return original order (good graceful path). No timeout, no batching (B5).
- **LLM:** OpenAI-compatible; prompt is sane (Vietnamese legal assistant, grounding instruction); citations returned are **all** contexts, not model-attributed ones.
- **Google Vision OCR:** dual credential path (inline env service-account fields, else `GOOGLE_APPLICATION_CREDENTIALS`); not exposed via API (B7).

## 6. Security / configuration findings

| # | Severity | Finding |
|---|----------|---------|
| S1 | **High** | Env-example drift. Root `.env.example` declares `ELASTICSEARCH_DENSE_INDEX` / `ELASTICSEARCH_SPARSE_INDEX`, `DEFAULT_RETRIEVAL_MODE`, `DEFAULT_TEMPERATURE`, `BACKEND_HOST` — **none read by `config.py`**. Meanwhile `config.py` reads `ELASTICSEARCH_INDEX/ALIAS`, `ELASTICSEARCH_VERIFY_CERTS`, `ELASTICSEARCH_REQUEST_TIMEOUT`, `RUNTIME_FALLBACK_ENABLED`, `ELASTIC_API_KEY`/`ELASTIC_USERNAME`/`ELASTIC_PASSWORD` fallbacks, `NEO4J_*` — several missing from root example. Three example files (root, `src/infra/.env.example`, `src/infra/production.env.example`) disagree. |
| S2 | OK | `src/infra/production.env` exists locally but is **git-ignored and not tracked** (`.gitignore:45 *.env`; verified via `git ls-files` / `git check-ignore`). Recommend a one-time history scan (`git log --all --diff-filter=A -- '*.env'`) and rotation if it ever appeared. |
| S3 | Medium | Backend port `8000` is host-published in production compose alongside nginx — API reachable directly, bypassing any future nginx-level controls. Restrict to the docker network or bind `127.0.0.1`. |
| S4 | Low | Root `.env.example` ships `NEO4J_PASSWORD=password` — weak placeholder invites copy-paste use. `production.env.example` correctly uses `<neo4j-password>` style. |
| S5 | Low | CD (`deploy.yml`) has no post-deploy health gate or rollback; deploys as `root` by default; `docker compose up` before verifying build health. |
| S6 | Low | CI installs both root and backend requirements and runs the **entire** `tests/` suite (incl. `test_neo4j_verification.py`, 27 tests; `test_elasticsearch_*`) — verify each live-service test self-skips without credentials, otherwise CI is red/flaky by construction. No lint (ruff) or type-check (mypy/pyright) step. |

## 7. Risks and missing tests

Existing coverage is decent for: runtime fallback, settings env reads, ES retriever mapping/filters, Voyage rerank ordering, OpenAI answer service, infra config lint, pipeline artifacts.

Missing:

- `FusionRetriever.merge` (RRF math, dedupe, score merge, rank reassignment) — untested.
- `build_filter_clauses`: `ranges`, `doc_id` list coercion, `.keyword` suffixing — untested.
- `ContextAssembler` dedupe of graph chunks — untested (and currently dead, B6).
- `GraphRetriever` Cypher behavior with mocked driver (center resolution, direction, relation filter) — untested.
- `IntentDetector` — untested.
- `config._getenv_int` / `_getenv_bool` malformed input — untested (B9).
- `/search` route (only `/answer` covered), validation-error responses (candidate_k < top_k → 422 vs 500), `/documents/*` routes — untested.
- OCR service — untested (needs fake Vision client).
- No upper-bound tests because no upper bounds exist (B3).

## 8. Prioritized fixes

1. **B1** — implement real dense retrieval (or stop pretending: alias `dense→sparse` explicitly and reject `hybrid` double-query). Prereq for the search phase.
2. **B3 + I2** — cap `top_k` (≤50) / `candidate_k` (≤200), server-side allowlist for rerank model; add basic rate limit or shared-secret header at nginx.
3. **B2** — wrap retrieval/answer path in a global exception handler returning structured 502/503 with `warnings`; ping ES/Neo4j at build to make `status` truthful.
4. **S1** — reconcile the three env example files to exactly the variables `config.py` reads (plus infra-only vars, clearly sectioned).
5. **B6** — make graph context real: populate `related_chunks` from neighbor docs via ES lookup; honor `max_hops`.
6. **B4** — replace `lru_cache` with app-lifespan state plus lazy re-init / live health probes.
7. **B5** — enforce `max_context_chunks`, Voyage timeout.
8. **F2** — label handoff as demo or remove.
9. **S6** — CI: add ruff + skip-guard audit for live-service tests.

## 9. Candidate quick fixes (small, low-risk, high value)

- Add `le=` bounds on `top_k`, `candidate_k`, `max_hops`, `timeout_ms` in `schemas.py` (one-line each).
- `RerankConfig.model` default → `rerank-2.5` (align with schema).
- Try/except in `_getenv_int` → fall back to default.
- `source_excludes` note: also exclude other large fields if mapping grows; already excludes `vector` twice (query + `.pop`) — keep one.
- Remove `google-cloud-compute`, `boto3` from backend requirements (verify no infra script imports them from this file first).
- Add `.dockerignore` (`data/`, `.git/`, `pipeline/`, `docs/`, `node_modules/`).
- Frontend Dockerfile: copy only `*.html *.css *.js *.svg` (or a `public/` subdir) instead of the whole directory.
- nginx: add `gzip on`, basic cache headers for static assets, `add_header X-Content-Type-Options nosniff`.
- `/documents/{doc_id}/version-chain`: return `{"implemented": false}` marker or 501 until built.
- Bind backend host port to `127.0.0.1:8000` in production compose.
