# Infrastructure

Target location for Docker Compose files, deployment configs, and environment templates.

## Architecture Overview

The MVP demo stack packages a single FastAPI API container. Elasticsearch Cloud, Neo4j VPS, and Google Cloud Vision OCR are **external services** — they are NOT started by Docker Compose. The API container connects to them via environment variables.

```
┌──────────────────────────────────────┐
│         Docker Compose                │
│  ┌──────────┐                        │
│  │   API    │──► Elasticsearch Cloud │
│  │  :8000   │──► Neo4j VPS           │
│  │          │──► Google Cloud Vision  │
│  └──────────┘                        │
└──────────────────────────────────────┘
```

## External Dependencies

| Service | Role | Configuration |
|---------|------|---------------|
| Elasticsearch Cloud | Dense + sparse retrieval | `ELASTICSEARCH_URL`, `ELASTICSEARCH_API_KEY`, `ELASTICSEARCH_DENSE_INDEX`, `ELASTICSEARCH_SPARSE_INDEX` |
| Neo4j VPS | Knowledge Graph traversal | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` |
| Google Cloud Vision | OCR for document processing | `GOOGLE_APPLICATION_CREDENTIALS` |
| Reranker | Cross-encoder reranking | `RERANK_PROVIDER`, `RERANK_MODEL`, `JINA_API_KEY`, `VOYAGE_API_KEY` |
| LLM Provider | Answer generation | `LLM_PROVIDER` |

## Environment Variables

Copy the example file and fill in real values:

```powershell
Copy-Item src/infra/.env.example src/infra/.env
```

| Variable | Description | Example |
|----------|-------------|---------|
| `BACKEND_PORT` | API listen port | `8000` |
| `ELASTICSEARCH_URL` | Elasticsearch Cloud endpoint | `https://....es.us-central1.gcp.cloud.es.io:9243` |
| `ELASTICSEARCH_API_KEY` | Elasticsearch API key | (from Elastic Cloud console) |
| `ELASTICSEARCH_DENSE_INDEX` | Index name for dense vector chunks | `vietlegal_dense` |
| `ELASTICSEARCH_SPARSE_INDEX` | Index name for sparse retrieval chunks | `vietlegal_sparse` |
| `NEO4J_URI` | Neo4j VPS Bolt URI | `bolt://your-vps:7687` |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | (set on VPS) |
| `NEO4J_DATABASE` | Neo4j database name | `neo4j` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path inside container to GCP service account JSON | `/app/credentials/google-service-account.json` |
| `RERANK_PROVIDER` | Reranker backend (`jina` or `voyage`) | `jina` |
| `RERANK_MODEL` | Reranker model name | `BAAI/bge-reranker-v2-m3` |
| `JINA_API_KEY` | Jina AI API key | `jina_...` |
| `VOYAGE_API_KEY` | Voyage AI API key | `pa-...` |
| `LLM_PROVIDER` | LLM backend | `mock` (MVP default) |
| `FRONTEND_ORIGIN` | CORS allowed origin | `http://localhost:5173` |

## Google Cloud Vision Credentials

The API container expects a GCP service account JSON file at
`/app/credentials/google-service-account.json` inside the container.
This file is mounted read-only from the host directory `./credentials`:

```powershell
# On the host, place your service-account key here:
mkdir credentials
cp /path/to/your-service-account-key.json credentials/google-service-account.json
```

- The `credentials/` directory is **gitignored**.
- **Never commit** service-account JSON files to the repository.
- The mount is defined in `docker-compose.yml` as `./credentials:/app/credentials:ro`.

## Build

```powershell
docker compose `
    --env-file src/infra/.env `
    -f src/infra/docker-compose.yml `
    build api
```

## Run

```powershell
docker compose `
    --env-file src/infra/.env `
    -f src/infra/docker-compose.yml `
    up --build
```

API health check:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

The container also includes a Docker healthcheck that probes `GET /health`
using Python (no curl required).

## Local Development Workflow

1. **Set up external services** — Ensure Elasticsearch Cloud and Neo4j VPS are reachable.
2. **Copy and edit env** — `Copy-Item src/infra/.env.example src/infra/.env` then fill in real credentials.
3. **Place GCP credentials** — `mkdir credentials && cp /path/to/key.json credentials/google-service-account.json`.
4. **Build and run** — Use the `docker compose up --build` command above.
5. **Run backend tests locally** — `python -m pytest tests/test_api_contract.py -q` (does not require Docker).
6. **Iterate** — Source code is not bind-mounted; rebuild the image after code changes with `docker compose build api`.

## Adding Local Elasticsearch / Neo4j (Offline Dev)

If external services are unavailable, create an override file:

```yaml
# src/infra/docker-compose.offline.yml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.13.4
    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"
      ES_JAVA_OPTS: "-Xms1g -Xmx1g"
    ports:
      - "9200:9200"

  neo4j:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: neo4j/password
    ports:
      - "7474:7474"
      - "7687:7687"
```

Then start with both compose files:

```powershell
docker compose `
    --env-file src/infra/.env `
    -f src/infra/docker-compose.yml `
    -f src/infra/docker-compose.offline.yml `
    up --build
```

Update `.env` to point at local services:

```dotenv
ELASTICSEARCH_URL=http://elasticsearch:9200
ELASTICSEARCH_API_KEY=
ELASTICSEARCH_DENSE_INDEX=vietlegal_dense
ELASTICSEARCH_SPARSE_INDEX=vietlegal_sparse
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j
```

## Neo4j VPS Profile (MVP)

- 2 vCPU
- ~2–2.4 GB RAM available
- 8 GB swap
- zRAM enabled
- ~24 GB free disk

Because the Neo4j VPS is small, MVP graph traversal remains one-hop and `raw_label` must be preserved on every relationship edge.
