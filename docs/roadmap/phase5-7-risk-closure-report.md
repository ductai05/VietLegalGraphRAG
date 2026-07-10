# Phase 5 to 7 Risk Closure Report

Date: 2026-07-08

Scope: close remaining risks except the LLM endpoint transport choice, then
finish frontend, infra, CI, Docker, Bruno, and documentation verification.

## Implemented

### Backend runtime

- Backend can run locally with `--app-dir src/backend/app` without manually
  setting `PYTHONPATH`.
- OCR upload now validates PDF parseability and page count before calling the
  OCR provider.
- Reranker timeouts are enforced per request and timeout fallback keeps the
  original ranking.
- Google Vision credentials can be materialized from legacy inline env fields
  into an ignored JSON file.
- `.env` was scrubbed of inline `GOOGLE_SERVICE_ACCOUNT_*` fields and now uses
  `GOOGLE_APPLICATION_CREDENTIALS`.

### Graph and LightRAG

- Graph related-doc extraction now supports live Neo4j nodes that use only
  `id=doc:<id>` and no `doc_id` property.
- Graph retrieval no longer stops at the first search hit when that document
  has no supported legal edges. It tries ordered retrieval hits until it finds
  a graph context with edges or related chunks.
- LightRAG context limiting now keeps at least one graph chunk when graph data
  exists and `max_context_chunks` would otherwise cut it off.
- Bruno local sample `docId` was changed to `399681`, a live document with
  graph edges.

### Frontend

- Frontend API base resolution works for direct local file/nginx usage and
  production `/api` proxy usage.
- Requests use `AbortController` timeout.
- OCR upload is wired from the frontend to `POST /documents/ocr`.
- OCR preview uses text-safe rendering.
- Handoff copy is explicitly demo-only.
- nginx config adds API rate limiting, gzip, cache headers, and security
  headers.
- Frontend Dockerfile copies only public static assets.

### Infra, CI, and Docker

- Production backend port is bound to localhost on the host.
- Deploy workflow waits for backend `/health` after backend updates.
- CI blocks tracked non-example env files and runs Ruff.
- CI and backend Dockerfile install Torch from the CPU-only PyTorch wheel index
  instead of pulling default CUDA wheels.
- Docker builds completed:
  - `vietlegal-frontend:local`, 73.8 MB
  - `vietlegal-backend:local`, 1.92 GB

## Live Verification

Backend was started with:

```powershell
conda run -n ml_env python -m dotenv -f .env run -- python -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir src/backend/app
```

Health:

```text
status=ok
elasticsearch=configured
neo4j=configured
embedding=local-hf
dense_retrieval=configured
reranker=voyage
ocr=google
warnings=[]
```

Bruno:

```text
01_health (200 OK)
02_search_sparse (200 OK)
03_search_dense (200 OK)
04_search_hybrid_rerank (200 OK)
05_answer_graph_llm (200 OK)
06_document_graph (200 OK)
07_version_chain (200 OK)
08_ocr_upload (200 OK)
Status: PASS, 8/8 requests
```

Live API summaries:

```text
hybrid_results=3
search_warnings=[]
graph_nodes=7
graph_edges=12
ocr_text_len=17
ocr_pages=1
```

LightRAG after graph fixes:

```text
trace_graph_hits=1
graph_chunks_used=1
graph_related_chunks=1
graph_edges=2
warnings=[]
```

Neo4j live graph inventory:

```text
Document nodes: 353,746
Article nodes are connected by Document -> HAS_CHUNK -> Article
Top relationship types include HAS_CHUNK, NEXT_CHUNK, PARENT_OF, IN_SECTOR,
HAS_LEGAL_TYPE, ISSUED_BY, CITES, GUIDELINES, AMENDS, REPEALS.
```

Version-chain remains empty because the live Neo4j database currently does not
contain `VERSION_OF` or `REPLACED_BY` relationship types.

## Verification Commands

```powershell
conda run -n ml_env python -m ruff check src/backend/app src/backend/services src/infra/scripts tests
conda run -n ml_env python -m pytest tests -q --tb=short
docker compose -f src/infra/docker-compose.yml config --quiet
docker compose -f src/infra/docker-compose.production.yml config --quiet
docker build -f src/frontend/Dockerfile -t vietlegal-frontend:local .
docker build -f src/backend/Dockerfile -t vietlegal-backend:local .
Set-Location bruno
bru run --env Local
```

Latest results:

```text
ruff: All checks passed
pytest: 216 passed, 1 warning, 2 subtests passed
compose config: pass for local and production files
frontend docker build: pass
backend docker build: pass with torch-2.12.1+cpu
Bruno: 8/8 requests passed
```

## Residual Risks

- LLM endpoint transport/security was intentionally not changed.
- Backend image remains large at 1.92 GB because local HF dense retrieval needs
  Torch and Transformers. It is now CPU-only, but still not lightweight.
- First runtime initialization can take longer than a short 5 second health
  timeout because Elasticsearch checks and local HF runtime load happen on the
  first runtime access.
- Version-chain endpoint returns an empty chain until graph import includes
  `VERSION_OF` or `REPLACED_BY`.
- Bruno currently checks HTTP status only. It is useful as a live smoke test,
  but it should gain assertions for response schema and minimum result counts.
