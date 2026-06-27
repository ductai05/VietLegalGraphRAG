# Backend

Target location for the FastAPI app, retrieval services, GraphRetriever, LightRAG orchestration, and answer generation services.

Do not move existing pipeline modules here without updating imports and tests.

## Runtime Services

- `services/retrieval_service.py`: resolves dense, sparse, hybrid and rerank execution modes.
- `services/graph_retriever.py`: reads legal graph context from Neo4j.
- `services/lightrag_service.py`: orchestrates retrieval, graph expansion and answer generation.
- `app/`: FastAPI application, request schemas and routes.

## MVP Decisions

- **`include_trace`:** The ``/answer`` endpoint **always** returns
  ``retrieval_trace`` during the MVP, regardless of the
  ``include_trace`` request field.  The field is accepted for forward
  compatibility but intentionally ignored.  Frontends MUST expect
  ``retrieval_trace`` to be present in every valid response.

