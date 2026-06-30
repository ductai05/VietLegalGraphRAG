# Infrastructure

Target location for Docker Compose files, deployment configs, and environment templates.

MVP infrastructure should prioritize a reproducible local or single-server demo stack.

## Demo Stack

The final MVP demo stack packages the FastAPI API container and connects to external services:

- Elasticsearch Cloud for dense and sparse retrieval.
- A dedicated Neo4j VPS for Knowledge Graph traversal.
- Google Cloud Vision OCR via a Google Service Account JSON credential.

Docker Compose should not start local Elasticsearch or local Neo4j in the default MVP demo path. Those services are configured through environment variables.

## External Service Assumptions

Neo4j VPS profile for MVP:

- 2 vCPU.
- Approximately 2 to 2.4 GB RAM available.
- 8 GB swap.
- zRAM enabled.
- Approximately 24 GB free disk.

Because the Neo4j VPS is small, MVP graph traversal remains one-hop and `raw_label` must be preserved on every relationship edge.

## Task 10 Direction

Task 10 continues as Docker/demo infrastructure, but it should build only the API demo container by default. It should provide env placeholders for:

- Elasticsearch Cloud URL/API key/index names.
- Neo4j VPS Bolt URI/user/password/database.
- Google Vision credential path.
- LLM provider/API key.
- Reranker provider/model while keeping both Jina AI and Voyage AI evaluable.
