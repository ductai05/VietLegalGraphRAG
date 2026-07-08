# Implementation Plan — Search, OCR, Graph Integration

Status: DRAFT — awaiting approval. No source changes until sign-off.
Companion docs: `-audit.md` (findings B*/F*/S*/I*), `-spec.md` (contracts), `-tasks.md` (task breakdown).

Ordering principle: hardening first (cheap, unblocks everything), then dense search (largest risk), then graph, then OCR, then frontend/infra/CI polish. Each phase is independently shippable and reviewable (< ~400 LOC diff target).

---

## Phase 0 — Guardrails and truthful runtime (no behavior redesign)

Fixes: B2, B3, B9, B12, I1, quick fixes.

1. `schemas.py`: bounds — `top_k ≤ 50`, `top_k ≤ candidate_k ≤ 200`, `max_hops ≤ 2`, `timeout_ms ≤ 120000`; rerank-model allowlist validator.
2. `retrieval_modes.py`: mirror the same bounds in dataclass `__post_init__`; align `RerankConfig.model` default to `rerank-2.5` (B8).
3. `config.py`: `_getenv_int` catches `ValueError` → default + startup warning.
4. `main.py`: global exception handler → structured `{"error", "detail", "warnings"}`; 502 for upstream errors; strip exception class names from client-visible warnings (sanitize in `dependencies.py`).
5. `routes/health.py`: `extractive`/`noop` only degrade when an upgraded provider was requested (compare against `Settings`).
6. Small cleanups: remove `google-cloud-compute`/`boto3` from backend requirements (grep infra scripts first); add `.dockerignore`.

- Depends on: nothing. Risk: low. Tests: bounds 422s, config parsing, handler shape, health matrix.

## Phase 1 — Live health probes and service lifecycle

Fixes: B4, B10.

1. Replace `@lru_cache` singleton with app-lifespan state (`app.state.runtime`); keep one-time build but add `probe()` (ES `ping`, Neo4j `verify_connectivity`) with 30 s result cache used by `/health`.
2. `_elasticsearch_is_configured`: require URL explicitly or default-URL-with-auth warning.
3. Optional re-init: if built in fallback and probes now succeed, rebuild once (guarded, logged).

- Depends on: Phase 0 (handler). Risk: medium (test reload patterns rely on module-level cache — update `test_backend_runtime_integration.py` reload helper). Tests: probe caching, degraded flip, re-init path.

## Phase 2 — Real dense retrieval + honest hybrid (core)

Fixes: B1. Spec §6.

1. `config.py`: `EMBEDDING_PROVIDER/MODEL/API_KEY` settings.
2. New `services/embedding_service.py`: `VoyageEmbedder` / `OpenAICompatibleEmbedder` / `NoneEmbedder` behind a `Protocol` (reuse existing client libs — no new deps).
3. New `ElasticsearchDenseRetriever` (same module as text retriever): `knn` query, same `build_filter_clauses`, maps via existing `retrieval_hit_from_elasticsearch` with `scores={"dense": _score}`.
4. `dependencies.py`: wire dense retriever when embedder configured; else sparse-alias + `dense_unavailable` warning; drop the permanent `dense_vector_query_unavailable` warning.
5. Startup dim check vs index mapping (`indices.get_mapping` on the alias); mismatch → warning + dense disabled.
6. `retrieval_service.py`: unchanged logic now receives genuinely different retrievers; skip double-query when dense is aliased to sparse (hybrid → single sparse pass).

- Depends on: Phase 0–1. Risk: **high** — embedding model must match pipeline index-time model (`pipeline/03_embeddings`); verify model name/dims from pipeline config before wiring. **No reindexing planned**; if the index lacks a usable `vector` kNN mapping, this phase stops and escalates (reindex would be a separate, riskier phase — call out before running `src/infra/scripts/import_elasticsearch_hybrid.py` against production). Live services needed only for the optional smoke test; unit tests fully mocked.

## Phase 3 — Graph context into answers + version-chain

Fixes: B6, B11. Spec §9.

1. `graph_retriever.py`: honor `max_hops` (variable-length pattern, still `LIMIT 100`); seed doc via `IntentDetector.document_number` match, fallback top-hit.
2. Populate `related_chunks`: inject a chunk-fetcher callable (ES top-1 per neighbor doc, ≤3 docs, intent-prioritized relations) — keeps `GraphRetriever` unit-testable.
3. `lightrag_service.py`: enforce `llm.max_context_chunks` (retrieval first, graph fills remainder) (B5-part); add `graph_chunks_used`, latency segments to trace.
4. `routes/documents.py`: implement `version-chain` (AMENDS/REPEALS walk); 501-style marker removed.

- Depends on: Phase 1 (lifecycle), not Phase 2. Risk: medium (Cypher on real graph shape — validate against `tests/test_neo4j_verification.py` expectations). Tests: mocked-driver Cypher assertions, assembler dedupe, max_context_chunks, version-chain route.

## Phase 4 — OCR endpoint

Fixes: B7. Spec §7.

1. `ocr_service.py`: remove import-time `load_dotenv`; credentials via `Settings`; lazy client.
2. `routes/ocr.py`: `POST /documents/ocr` multipart; size cap (`OCR_MAX_FILE_MB`), mime allowlist, PDF page-count pre-check (add `pypdf` — the one justified new dependency), error mapping per spec §5.3.
3. `dependencies.py` + `/health`: `ocr: configured|disabled`.

- Depends on: Phase 0. Risk: low-medium (Vision quota/cost — endpoint should sit behind the same rate-limit stopgap). Tests: mocked Vision happy path, 413/415/422/503 paths. Live Vision smoke test requires credentials — mark and skip by default.

## Phase 5 — Frontend alignment

Fixes: F1, F2, F3, F5.

1. `chat.html`/`index.html`: set `window.AURORA_API_BASE` (inline script; dev fallback `http://localhost:8000` when served off `localhost` without nginx).
2. `app.js`: `AbortController` 30 s timeout; distinct timeout vs error copy; handoff bubble labeled "(demo — no attorney is contacted)"; optional OCR upload control posting to `/api/documents/ocr` and rendering extracted text preview (`textContent` only).
3. `src/frontend/Dockerfile`: copy only `*.html *.css *.js *.svg`; nginx: gzip, static cache headers, `X-Content-Type-Options`.

- Depends on: Phase 4 for upload UI (label rest independent). Risk: low. Tests: extend `test_frontend_backend_connection.py` static assertions (API base set, AbortController present, no fake-handoff claim without demo label).

## Phase 6 — Infra, CI, env reconciliation

Fixes: S1, S3, S5, S6, I2.

1. Regenerate root/.infra/.production env examples from `config.py` (sectioned; remove dead vars) — update `test_infra_deployment_config.py` accordingly.
2. Production compose: backend port bound `127.0.0.1:8000`; pass new `EMBEDDING_*`/OCR vars through.
3. nginx: simple rate limit (`limit_req`) on `/api/`; optional `API_SHARED_SECRET` header injection + backend check.
4. CI: add `ruff check`; add guard step asserting no tracked non-example `*.env`; audit live-service tests for skip guards (add `pytest.mark.skipif` on missing env where absent).
5. CD: post-deploy health gate (`curl /health` loop, fail job on timeout).

- Depends on: Phases 2–4 for env var list finality. Risk: low-medium (deploy script touches production — review carefully; health gate makes failures visible instead of silent).

## Phase 7 — Docs

1. Update `src/README.md`, `src/infra/README.md`, root README API section: endpoints, env matrix, failure modes, OCR limits, dense-model-must-match-index warning.
2. Record decisions (dense provider chosen, reindex deferred) in this roadmap directory.

---

## Risky steps called out (require explicit approval before execution)

- **Any ES reindex/mapping change** (only if Phase 2 discovers an unusable `vector` mapping) — production data, hours-long, needs alias cutover plan.
- **Deploy pipeline changes** (Phase 6.5) — touches production droplet.
- **Enabling dense retrieval in production** — new per-query embedding cost (Voyage/LLM provider billing); roll out behind `EMBEDDING_PROVIDER=none` default.

## Verification per phase

Every phase: `python -m pytest tests` green locally without live credentials; ruff clean (once added); targeted new tests listed in `-tasks.md`; no change to `/answer` response fields consumed by `app.js` (`answer`, `citations`, `retrieval_trace`).
