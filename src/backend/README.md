# Backend

Target location for the FastAPI app, retrieval services, GraphRetriever, LightRAG orchestration, and answer generation services.

Do not move existing pipeline modules here without updating imports and tests.

## Runtime Services

- `services/retrieval_service.py`: resolves dense, sparse, hybrid and rerank execution modes.
- `services/graph_retriever.py`: reads legal graph context from Neo4j.
- `services/lightrag_service.py`: orchestrates retrieval, graph expansion and answer generation.
- `app/`: FastAPI application, request schemas and routes.

## Final MVP Runtime Decisions

- Elasticsearch Cloud is the only retrieval backend.
- Neo4j runs on a dedicated VPS and provides one-hop graph expansion for the MVP.
- Google Cloud Vision provides OCR as an external managed service.
- Google Vision authentication uses a Google Service Account JSON credential.
- Local PaddleOCR is not part of the MVP runtime.
- LightRAG is only the orchestration layer. It does not replace hybrid Elasticsearch retrieval.
- Current answer generation remains `ExtractiveAnswerService`; a future LLM-backed `AnswerService` can replace it behind the same service contract.
- Default answer temperature is `0.2`.
- Reranker provider remains undecided; evaluate Jina AI and Voyage AI without locking the architecture to either provider.

## LightRAG Flow

```text
User Query
  -> Intent Detection
  -> Hybrid Elasticsearch Retrieval (Dense + Sparse)
  -> RRF
  -> Optional Rerank
  -> Document Resolution
  -> Optional Neo4j Graph Expansion
  -> Context Assembly
  -> LLM Answer
  -> Citation + Trace
```

MVP graph expansion remains one-hop and preserves `raw_label` on every graph edge.

`Document Resolution` in this flow is a logical orchestration step. A dedicated `DocumentResolver` module remains a future enhancement and should not be scheduled before current MVP completion.

## MVP Decisions

- **`include_trace`:** The ``/answer`` endpoint **always** returns
  ``retrieval_trace`` during the MVP, regardless of the
  ``include_trace`` request field.  The field is accepted for forward
  compatibility but intentionally ignored.  Frontends MUST expect
  ``retrieval_trace`` to be present in every valid response.
