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

## Neo4j Fresh Import

The setup script is destructive and requires `--yes-recreate`.

Upload CSV files:

```bash
ssh root@<DROPLET_IP> 'mkdir -p /opt/vietlegal/neo4j/import'
scp documents.csv articles.csv legal_types.csv authorities.csv sectors.csv root@<DROPLET_IP>:/opt/vietlegal/neo4j/import/
scp *_edges.csv root@<DROPLET_IP>:/opt/vietlegal/neo4j/import/
```

Run setup:

```bash
scp src/infra/setup_neo4j_droplet.sh root@<DROPLET_IP>:/tmp/
ssh root@<DROPLET_IP> 'bash /tmp/setup_neo4j_droplet.sh --yes-recreate "<neo4j-password>"'
```

The script deletes known old Neo4j containers and volumes, clears
`/opt/vietlegal/neo4j/data`, bulk imports the CSV files, and starts
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
