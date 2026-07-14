# Infrastructure

This directory contains Docker and Droplet deployment configuration for
VietLegalGraphRAG.

## Production Runtime Layout

Production uses three independent containers on one user-defined Docker bridge:

| Container | Managed by | Network name | Purpose |
|-----------|------------|--------------|---------|
| `vietlegal-neo4j` | `setup_neo4j_droplet.sh` | `vietlegal_net` | Neo4j graph database |
| `vietlegal-backend` | `docker-compose.production.yml` | `vietlegal_net` | FastAPI backend |
| `vietlegal-frontend` | `docker-compose.production.yml` | `vietlegal_net` | nginx static frontend |

Neo4j is not part of the app compose file. App deploys must not restart or
reimport Neo4j.

Droplet filesystem layout:

```text
/opt/vietlegal/
  env/production.env
  credentials/google-service-account.json
  neo4j/
    import/
    data/
    certs/
```

## Environment

Create the production env file on the Droplet:

```bash
mkdir -p /opt/vietlegal/env /opt/vietlegal/credentials
cp src/infra/production.env.example /opt/vietlegal/env/production.env
nano /opt/vietlegal/env/production.env
```

The backend connects to Neo4j over Docker bridge:

```dotenv
ELASTICSEARCH_INDEX=vietlegal_chunks_hybrid_v1
ELASTICSEARCH_ALIAS=vietlegal_chunks
NEO4J_URI=bolt://vietlegal-neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<neo4j-password>
NEO4J_DATABASE=neo4j
```

External admin clients can use:

```text
neo4j+ssc://<DROPLET_IP>:7687
https://<DROPLET_IP>:7473
```

For Google Vision OCR, prefer a JSON service account file:

```dotenv
OCR_PROVIDER=google
GOOGLE_APPLICATION_CREDENTIALS=/opt/vietlegal/credentials/google-service-account.json
```

If a local `.env` still contains legacy inline `GOOGLE_SERVICE_ACCOUNT_*`
fields, materialize them once into an ignored JSON file and scrub the inline
fields:

```bash
python src/infra/scripts/materialize_google_credentials.py \
  --env-file .env \
  --output credentials/google-service-account.json
```

The script prints only the output path and does not print secret values.

## Elasticsearch Hybrid Import

Use `scripts/import_elasticsearch_hybrid.py` when pipeline artifacts are ready.
It creates one Elasticsearch index, indexes sparse/text payload first, then
updates dense vectors into the same documents by `chunk_id`.

Expected local artifact layout:

```text
data/retrieval/
  sparse/bm25_v0.1/sparse_payload.parquet
  dense/vnlegal_lal_v0.1/
    manifest.json
    payload/*.parquet
    vectors/*.npy
```

Install host-side import dependencies:

```bash
python -m pip install -r requirements.txt
```

Run a fresh import:

```bash
python src/infra/scripts/import_elasticsearch_hybrid.py \
  --env-file src/infra/production.env \
  --recreate \
  --index vietlegal_chunks_hybrid_v1 \
  --alias vietlegal_chunks \
  --sparse-max-chunk-mb 8 \
  --dense-max-chunk-mb 8
```

Operational notes:

- `--recreate` deletes and recreates only the target Elasticsearch index.
- The checkpoint defaults to `data/retrieval/elasticsearch_hybrid_ingest_checkpoint.json`.
- Bad or oversized records are written to the `.deadletter.jsonl` file.
- Dense import skips duplicate `chunk_id` rows and records `duplicates_skipped`
  in the checkpoint instead of updating the same Elasticsearch document twice.
- Trial tier imports should keep `--sparse-max-chunk-mb` and
  `--dense-max-chunk-mb` modest, for example 5 to 10 MB, to avoid repeated
  429/timeout retries.
- `--max-error-rate` defaults to `0.01`, so up to 1 percent bad records can be
  tolerated before the script stops.
- For a smoke run, use `--max-sparse-rows 10000 --max-dense-shards 1`.

## Neo4j Fresh Import

The setup script is destructive and requires `--recreate`.

Upload graph CSV files and recreate Neo4j:

```bash
bash src/infra/scripts/import_neo4j_droplet.sh \
  --host <DROPLET_IP> \
  --user root \
  --ssh-port 22 \
  --source data/retrieval/graph/kg_v0.1 \
  --neo4j-password "<neo4j-password>" \
  --recreate
```

Upload only, without recreating Neo4j:

```bash
bash src/infra/scripts/import_neo4j_droplet.sh \
  --host <DROPLET_IP> \
  --source data/retrieval/graph/kg_v0.1 \
  --upload-only
```

The wrapper uploads CSVs from the source root, `nodes/`, and `edges/` into
`/opt/vietlegal/neo4j/import`. With `--recreate`, it uploads and runs
`setup_neo4j_droplet.sh`, which deletes known old Neo4j containers and volumes,
clears `/opt/vietlegal/neo4j/data`, bulk imports the CSV files, and starts
`vietlegal-neo4j` on `vietlegal_net`.

Use `docker restart vietlegal-neo4j` for a normal Neo4j restart. Use the setup
script only when you want to recreate/import the database.

## App Deploy

GitHub Actions deploys on pushes to `production`.

The deploy workflow:

- pulls the new `production` revision on the Droplet
- compares changed paths
- rebuilds backend only when backend or shared app config changed
- rebuilds frontend only when frontend or shared app config changed
- waits for backend `/health` after backend updates
- never restarts Neo4j

Manual app deploy:

```bash
cd /opt/VietLegalGraphRAG
docker network create vietlegal_net 2>/dev/null || true
docker compose --env-file /opt/vietlegal/env/production.env -f src/infra/docker-compose.production.yml build backend frontend
docker compose --env-file /opt/vietlegal/env/production.env -f src/infra/docker-compose.production.yml up -d --no-deps backend frontend
```

## Local Backend Compose

`docker-compose.yml` is still API-only for local development. It expects
Elasticsearch, Neo4j, Google Vision, reranker, and LLM providers to be supplied
through environment variables.

The backend Dockerfile installs PyTorch from the CPU-only PyTorch wheel index:

```text
https://download.pytorch.org/whl/cpu
```

This avoids pulling CUDA and cuDNN wheels on CPU droplets. The image is still
large because local dense retrieval uses Torch and Transformers.

Local verification commands:

```powershell
conda run -n ml_env python -m ruff check src/backend/app src/backend/services src/infra/scripts tests
conda run -n ml_env python -m pytest tests -q --tb=short
docker compose -f src/infra/docker-compose.yml config --quiet
docker compose -f src/infra/docker-compose.production.yml config --quiet
docker build -f src/backend/Dockerfile -t vietlegal-backend:local .
docker build -f src/frontend/Dockerfile -t vietlegal-frontend:local .
```
