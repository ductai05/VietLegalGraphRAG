# Local Live Demo Report: Phase 1 to Phase 3

Date: 2026-07-08

Scope:

- Run backend locally with `conda` env `ml_env`.
- Use real credentials from local `.env` without printing secrets.
- Verify Elasticsearch hybrid index, local HF dense embedding, Voyage rerank, Neo4j graph, OpenAI-compatible LLM, and Google Vision OCR.
- Fix live errors found during verification.
- Add a Bruno collection for repeatable API checks.

## Local Environment

- Python env: `ml_env`
- Python version: 3.12.13
- Backend dependencies installed from `src/backend/requirements.txt`
- Verified imports: FastAPI, Uvicorn, Neo4j, Elasticsearch stack, OpenAI, Voyage AI, Google Vision, Torch, Transformers, python-multipart
- Docker daemon available
- Docker Compose config parse: passed

Local `.env` adjustments:

- `LLM_PROVIDER=openai-compatible`
- `LLM_BASE_URL`: kept existing host and port, added `/v1`
- `OCR_PROVIDER=google`
- `EMBEDDING_CACHE_DIR=src/infra/hf-cache`

No secret values were added to the Bruno collection or this report.

## Fixes Applied During Live Verification

1. Google Vision OCR image request
   - File: `src/backend/services/ocr_service.py`
   - Problem: live OCR failed with `Unknown field for Image: image_context`.
   - Fix: pass `image_context` to `client.document_text_detection(...)`, not to `vision.Image`.

2. OpenAI-compatible LLM endpoint
   - File: local ignored `.env`
   - Problem: `/answer` returned 502 because the base URL pointed to a web page, not the OpenAI-compatible API path.
   - Fix: added `/v1` to the existing `LLM_BASE_URL`.

3. LLM runtime stability
   - File: `src/backend/services/lightrag_service.py`
   - Problem: any LLM upstream error turned `/answer` into a hard 502.
   - Fix: fallback to extractive answer and add sanitized trace code `llm.answer_failed`.

4. Neo4j version-chain warning noise
   - File: `src/backend/services/graph_retriever.py`
   - Problem: version-chain query emitted Neo4j warnings when `VERSION_OF` and `REPLACED_BY` relationship types were absent.
   - Fix: check `CALL db.relationshipTypes()` first and return an empty chain when version relations are not present.

5. Bruno API collection
   - Folder: `bruno/`
   - Added 8 requests: health, sparse search, dense search, hybrid rerank, answer, document graph, version chain, OCR upload.
   - Added local fixture: `bruno/fixtures/ocr-demo.png`

## Verification Commands

Install dependencies:

```powershell
conda run -n ml_env python -m pip install -r src/backend/requirements.txt
```

Dependency import check:

```powershell
conda run -n ml_env python -c "import fastapi, uvicorn, neo4j, torch, transformers, google.cloud.vision, voyageai, openai, multipart; print('deps_ok')"
```

Result:

```text
deps_ok
```

Targeted tests:

```powershell
conda run -n ml_env python -m pytest tests/test_ocr_service.py tests/test_graph_backend.py -q --tb=short
conda run -n ml_env python -m pytest tests/test_health_status.py tests/test_backend_runtime_integration.py -q --tb=short
```

Results:

```text
35 passed, 1 warning
17 passed, 1 warning
```

Full test suite:

```powershell
conda run -n ml_env python -m pytest tests -q --tb=short
```

Result:

```text
199 passed, 1 warning, 2 subtests passed in 37.12s
```

Docker Compose config:

```powershell
docker compose -f src/infra/docker-compose.yml config --quiet
```

Result:

```text
compose_config_ok
```

Start local backend:

```powershell
Set-Location -LiteralPath 'D:\Y3S2\[ML]_VietLegalGraphRAG'
$env:PYTHONPATH = "$PWD\src\backend\app;$PWD\src\backend\services"
conda run -n ml_env python -m dotenv -f .env run -- python -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir src/backend/app
```

Bruno CLI:

```powershell
Set-Location -LiteralPath 'D:\Y3S2\[ML]_VietLegalGraphRAG\bruno'
bru run --env Local
```

Result:

```text
8 requests, 8 passed
```

## Live API Results

In-process live smoke with real credentials:

- `GET /health`: 200, status `ok`, no warnings
- `POST /search` sparse: 200, 3 results
- `POST /search` dense: 200, 3 results
- `POST /search` hybrid: 200, 3 results
- `POST /search` hybrid with Voyage rerank: 200, 2 results
- `GET /documents/{doc_id}/graph`: 200, center found
- `GET /documents/{doc_id}/version-chain`: 200, empty chain, no Neo4j warning after fix
- `POST /answer` sparse with graph and LLM: 200, answer returned, 2 citations
- `POST /documents/ocr`: 200, Google Vision returned text

HTTP live smoke via `uvicorn`:

- `GET /health`: 200
- `POST /search` sparse: 200
- `POST /search` dense: 200
- `POST /search` hybrid: 200
- `GET /documents/{doc_id}/graph`: 200
- `POST /answer`: 200
- `POST /documents/ocr`: 200

## Current Risks

1. Local `.env` contains inline Google service-account fields. It works, but a credential file or external secret manager is safer.
2. Current LLM endpoint uses HTTP with an IP and port. If this is not a trusted local or private proxy, API traffic and keys can be exposed in transit.
3. Neo4j live sample returned one document node and zero edges. The graph service works, but the imported graph relationship coverage needs separate data quality verification.
4. Version-chain returns empty because the current Neo4j database does not expose `VERSION_OF` or `REPLACED_BY`.
5. First dense query may download or load `darklethelong/vnlegal-lal`; Windows may show Hugging Face symlink cache warnings. This is operational noise, not an API failure.
6. Backend local run still needs explicit `PYTHONPATH` because modules are imported as flat files, not as an installed package.
7. Docker image build was not run in this pass. Compose config was validated, and backend runtime was verified through `ml_env` plus live HTTP.
8. Test suite has one `StarletteDeprecationWarning` from FastAPI TestClient and `httpx`.

## Status

Backend local runtime is verified with real credentials through both direct FastAPI client and real HTTP server. Bruno collection is executable and passed all 8 requests against the local backend.
