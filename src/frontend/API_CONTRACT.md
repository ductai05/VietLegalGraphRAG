# Frontend API Contract

Frontend calls the FastAPI backend **only**.  It does **not** call Elasticsearch,
Neo4j, reranker models, or LLM providers directly.

## Base URL

```
http://localhost:8000
```

Configure via `BACKEND_HOST` / `BACKEND_PORT` as defined in `.env.example`.

## CORS

The backend sets `Access-Control-Allow-Origin` to the configured
`FRONTEND_ORIGIN` (default `http://localhost:5173`).  No wildcard origin is
allowed when `Access-Control-Allow-Credentials` is `true`.

---

## Endpoints

### `GET /health`

Reports backend service status.  Currently reports `"degraded"` / `"not_checked"`
— no live connectivity probes during the MVP.

**Response 200**

| Field           | Type   | Description                                |
|-----------------|--------|--------------------------------------------|
| `status`        | string | `"ok"` or `"degraded"`                     |
| `elasticsearch` | string | Currently `"not_checked"`                  |
| `neo4j`         | string | Currently `"not_checked"`                  |
| `llm`           | string | Provider key (currently `"mock"`)          |

Example:

```json
{
  "status": "degraded",
  "elasticsearch": "not_checked",
  "neo4j": "not_checked",
  "llm": "mock"
}
```

---

### `POST /search`

Retrieval-only endpoint.  Returns ranked document chunks without generating an
LLM answer.

**Request body** — `SearchRequestModel`

| Field             | Type    | Required | Default    | Description                                                                 |
|-------------------|---------|----------|------------|-----------------------------------------------------------------------------|
| `query`           | string  | yes      | —          | Search query.  Minimum 1 character.                                          |
| `retrieval_mode`  | string  | no       | `"hybrid"` | `"dense"`, `"sparse"`, or `"hybrid"`                                        |
| `rerank.enabled`  | bool    | no       | `true`     | Whether to apply cross-encoder rerank after retrieval.                        |
| `rerank.model`    | string  | no       | `"BAAI/bge-reranker-v2-m3"` | Rerank model name.                                             |
| `rerank.candidate_k` | int  | no       | `50`       | Number of candidates to fetch before rerank.  Must be ≥ `top_k`.            |
| `rerank.batch_size`  | int  | no       | `8`        | Rerank inference batch size.                                                |
| `rerank.device`   | string  | no       | `"auto"`   | Inference device.  Recommended values: `"auto"`, `"cpu"`, `"cuda"`.  Backend currently accepts any string. |
| `rerank.timeout_ms`  | int  | no       | `30000`    | Rerank timeout in milliseconds.                                             |
| `top_k`           | int     | no       | `5`        | Number of results to return.  Must be positive.                              |
| `filters`         | object  | no       | `{}`       | Key-value metadata filters.  See [Filter Keys](#filter-keys) below.          |
| `graph.enabled`   | bool    | no       | `true`     | Whether graph expansion is enabled.                                          |
| `graph.use_lightrag` | bool | no       | `true`     | Whether to use LightRAG orchestration.                                       |
| `graph.max_hops`  | int     | no       | `1`        | Graph traversal depth.  Must be ≥ 0.                                         |
| `llm.temperature` | float   | no       | `0.2`      | LLM temperature.  Range `0.0` – `1.0`.                                       |
| `llm.max_context_chunks` | int | no    | `8`        | Maximum context chunks passed to LLM.  Must be positive.                     |
| `include_trace`   | bool    | no       | `true`     | Reserved for forward compatibility.  **Ignored during MVP** — trace is always returned. |

### Filter Keys

The `filters` object supports the following keys during the MVP.  Filters are
applied as metadata constraints on Elasticsearch document fields.

| Key                  | Type   | Description                                           |
|----------------------|--------|-------------------------------------------------------|
| `effect_status`      | string | Legal effect status (e.g. `"Con hieu luc"`).          |
| `legal_type`         | string | Document type (e.g. `"Luat"`, `"Nghi dinh"`).         |
| `legal_sector`       | string | Legal sector or domain.                                |
| `issuing_authority`  | string | Issuing body (e.g. `"Quoc hoi"`, `"Chinh phu"`).      |
| `document_number`    | string | Exact document number match (e.g. `"01/2026/QH"`).    |

**Pass-through behavior:**
- Unknown filter keys are passed through to the backend as-is.
- Unsupported filters may be silently ignored during the MVP.
- The frontend should limit itself to the documented keys for predictable
  results.

**Validation errors → 422**

| Condition                                         |
|---------------------------------------------------|
| `query` is empty or missing                       |
| `retrieval_mode` is not `dense`/`sparse`/`hybrid` |
| `top_k` ≤ 0                                       |
| `rerank.candidate_k` ≤ 0                          |
| `rerank.batch_size` ≤ 0                           |
| `rerank.timeout_ms` ≤ 0                           |
| `llm.temperature` < 0.0 or > 1.0                   |
| `llm.max_context_chunks` ≤ 0                      |
| `graph.max_hops` < 0                              |
| `rerank.enabled` is true and `rerank.candidate_k` < `top_k` |

**Response 200**

| Field             | Type            | Description                                   |
|-------------------|-----------------|-----------------------------------------------|
| `query`           | string          | Echoed query.                                  |
| `retrieval_mode`  | string          | Executed retrieval mode.                       |
| `execution_mode`  | string          | Resolved execution mode (e.g. `"hybrid_rerank"`). |
| `latency_ms`      | integer         | End-to-end latency (demo returns 0).           |
| `results`         | array of object | `RetrievalHit` items ordered by rank.          |
| `warnings`        | array of string | Service warnings (demo returns `["demo_dependency"]`). |

**`RetrievalHit` fields**

| Field             | Type    | Description                                    |
|-------------------|---------|------------------------------------------------|
| `rank`            | integer | Rank position (1-indexed).                     |
| `chunk_id`        | string  | Unique chunk identifier.                       |
| `doc_id`          | string  | Parent document identifier.                    |
| `title`           | string  | Document title.                                |
| `document_number` | string  | Legal document number (e.g. `"01/2026/QH"`).   |
| `legal_type`      | string  | Document type (`"Luat"`, `"Nghi dinh"`, etc.). |
| `effect_status`   | string  | Legal effect status.                           |
| `section_path`    | string  | Path within the document (e.g. `"Dieu 1"`).    |
| `text`            | string  | Chunk text content.                            |
| `scores`          | object  | Score map (e.g. `{"rrf": 0.03}`).              |
| `citation`        | string  | Human-readable citation.                       |

### Reusable Types

These types appear in graph endpoints and `/answer`'s `graph_context`.

#### `GraphNode`

| Field        | Type            | Description                                 |
|--------------|-----------------|---------------------------------------------|
| `id`         | string          | Unique node identifier (e.g. `"doc:42"`).    |
| `label`      | string          | Node label (e.g. `"Document"`).              |
| `properties` | object          | Arbitrary key-value metadata for the node.   |

Example:

```json
{
  "id": "doc:42",
  "label": "Document",
  "properties": {
    "doc_id": "42",
    "title": "Luat Xay dung",
    "document_number": "01/2026/QH"
  }
}
```

#### `GraphEdge`

| Field       | Type   | Description                                                   |
|-------------|--------|---------------------------------------------------------------|
| `source`    | string | Source node `id`.                                              |
| `target`    | string | Target node `id`.                                              |
| `type`      | string | Canonical relationship type: `"AMENDS"`, `"CITES"`, `"REPEALS"`, or `"GUIDELINES"`. |
| `raw_label` | string | Original Vietnamese relationship label (e.g. `"Van ban can cu"`). |
| `direction` | string | `"out"` (center → neighbor) or `"in"` (neighbor → center).     |
| `properties`| object | Arbitrary key-value metadata for the edge.                     |

Example:

```json
{
  "source": "doc:42",
  "target": "doc:99",
  "type": "CITES",
  "raw_label": "Van ban can cu",
  "direction": "out",
  "properties": {}
}
```

#### `AnswerContext`

| Field      | Type            | Description                                                   |
|------------|-----------------|---------------------------------------------------------------|
| `source`   | string          | Origin: `"retrieval"` or `"graph"`.                           |
| `chunk_id` | string \| null  | Chunk identifier (nullable when chunk is unknown).             |
| `doc_id`   | string          | Parent document identifier.                                   |
| `title`    | string          | Document title.                                               |
| `text`     | string          | Chunk text content.                                           |
| `citation` | string          | Human-readable citation.                                      |
| `relation` | string \| null  | Relationship to query document (graph contexts only).          |
| `raw_label`| string \| null  | Original Vietnamese relationship label (graph contexts only). |

Example:

```json
{
  "source": "graph",
  "chunk_id": "chunk:99:000001",
  "doc_id": "99",
  "title": "Nghi dinh 15/2021/ND-CP",
  "text": "Dieu 5 quy dinh chi tiet ve...",
  "citation": "Nghi dinh 15/2021/ND-CP, Dieu 5",
  "relation": "CITES",
  "raw_label": "Van ban can cu"
}
```

**Example request**

```json
{
  "query": "Dieu kien cap giay phep xay dung la gi?",
  "retrieval_mode": "hybrid",
  "rerank": {"enabled": false},
  "top_k": 2,
  "filters": {"effect_status": "Con hieu luc"},
  "graph": {"enabled": false, "use_lightrag": false, "max_hops": 1},
  "llm": {"temperature": 0.2, "max_context_chunks": 8}
}
```

**Example response** — see `mocks/search_response.json` for a realistic snapshot.

---

### `POST /answer`

Returns answer, citations, retrieval context, graph context, and trace.

**Request body** — same `SearchRequestModel` as `/search` (all fields identical).

**Validation errors → 422** — same rules as `/search`.

**Response 200**

| Field               | Type            | Description                                          |
|---------------------|-----------------|------------------------------------------------------|
| `answer`            | string          | Generated or extractive answer text.                 |
| `citations`         | array of object | `{chunk_id, doc_id, title}` per cited source.        |
| `retrieval_context` | array of object | `RetrievalHit` items used as context.                |
| `graph_context`     | object          | `GraphContext` payload (empty `{}` when graph disabled or demo). |
| `retrieval_trace`   | object          | Execution metadata.  **Always present during MVP.**  |
| `latency_ms`        | integer         | End-to-end latency (demo returns 0).                 |

**`retrieval_trace` fields**

| Field              | Type    | Description                                         |
|--------------------|---------|-----------------------------------------------------|
| `retrieval_mode`   | string  | Requested retrieval mode.                           |
| `execution_mode`   | string  | Resolved execution mode.                            |
| `reranked`         | bool    | Whether rerank was applied.                         |
| `temperature`      | float   | LLM temperature used.                               |
| `graph_enabled`    | bool    | Whether graph was requested.                        |
| `lightrag_enabled` | bool    | Whether LightRAG orchestration ran (demo: `false`). |

**MVP behavior: `include_trace`**

The `include_trace` request field is reserved for forward compatibility.
During the MVP, `retrieval_trace` is **always** included in the response
regardless of the field value.  The frontend MUST expect `retrieval_trace`
to be present in every valid `/answer` response.

**Example request**

```json
{
  "query": "Van ban nao sua doi quy dinh nay?",
  "retrieval_mode": "hybrid",
  "rerank": {"enabled": true, "candidate_k": 5},
  "top_k": 2
}
```

**Example response** — see `mocks/answer_response.json` for a realistic snapshot.

---

### `GET /documents/{doc_id}/graph`

Returns the knowledge graph neighborhood for a document.

**Path parameters**

| Parameter | Type   | Description                 |
|-----------|--------|-----------------------------|
| `doc_id`  | string | Document identifier.        |

**Response 200**

| Field            | Type            | Description                                     |
|------------------|-----------------|-------------------------------------------------|
| `center`         | object \| null  | Center document `{id, label, properties}`.      |
| `nodes`          | array           | `GraphNode` items in the neighborhood.          |
| `edges`          | array           | `GraphEdge` items (includes `raw_label`).       |
| `related_chunks` | array           | `AnswerContext` items from related documents.   |
| `query_intent`   | string          | Detected intent (default `"general"`).          |

**MVP status:** Contract-stable but backed by a demo/stub implementation.
Returns the center document with empty `nodes`, `edges`, and `related_chunks`
until runtime Neo4j wiring is completed.

Example:

```json
{
  "center": {
    "id": "doc:42",
    "label": "Document",
    "properties": {"doc_id": "42"}
  },
  "nodes": [],
  "edges": [],
  "related_chunks": [],
  "query_intent": "general"
}
```

**Illustrative response shape** *(once Neo4j wiring is complete)*

The example below shows the expected response shape when the graph backend is
fully wired.  **Current MVP runtime may still return stub data.**

```json
{
  "center": {
    "id": "doc:42",
    "label": "Document",
    "properties": {
      "doc_id": "42",
      "title": "Luat Xay dung 2014",
      "document_number": "50/2014/QH13"
    }
  },
  "nodes": [
    {
      "id": "doc:99",
      "label": "Document",
      "properties": {
        "doc_id": "99",
        "title": "Nghi dinh 15/2021/ND-CP",
        "document_number": "15/2021/ND-CP"
      }
    }
  ],
  "edges": [
    {
      "source": "doc:42",
      "target": "doc:99",
      "type": "GUIDELINES",
      "raw_label": "Van ban huong dan",
      "direction": "out",
      "properties": {}
    }
  ],
  "related_chunks": [
    {
      "source": "graph",
      "chunk_id": "chunk:99:000001",
      "doc_id": "99",
      "title": "Nghi dinh 15/2021/ND-CP",
      "text": "Dieu 5 quy dinh chi tiet ve ho so cap giay phep xay dung...",
      "citation": "Nghi dinh 15/2021/ND-CP, Dieu 5",
      "relation": "GUIDELINES",
      "raw_label": "Van ban huong dan"
    }
  ],
  "query_intent": "guideline"
}
```

---

### `GET /documents/{doc_id}/version-chain`

Returns the legal amendment chain for one document.

**Path parameters**

| Parameter | Type   | Description                 |
|-----------|--------|-----------------------------|
| `doc_id`  | string | Document identifier.        |

**Response 200**

| Field   | Type   | Description                                    |
|---------|--------|------------------------------------------------|
| `doc_id`| string | Echoed document identifier.                    |
| `chain` | array  | Ordered version chain items (demo: empty).     |

**MVP status:** Contract-stable but backed by a demo/stub implementation.
Returns an empty `chain` until runtime Neo4j wiring is completed.

Example:

```json
{
  "doc_id": "42",
  "chain": []
}
```

---

## MVP Runtime Constraints

1. **Frontend communicates ONLY with the FastAPI backend** — all API calls to
   `http://localhost:8000` (or configured `BACKEND_HOST`/`BACKEND_PORT`).

2. **Frontend never accesses Elasticsearch directly** — retrieval is
   abstracted behind `/search` and `/answer`.

3. **Frontend never accesses Neo4j directly** — graph data is abstracted
   behind `/documents/{doc_id}/graph` and `/documents/{doc_id}/version-chain`,
   and is embedded in `/answer` responses (graph_context, retrieval_trace).

4. **`retrieval_trace` is ALWAYS returned by `/answer`** during the MVP.
   The `include_trace` request field is accepted for forward compatibility
   only and is intentionally ignored.

5. **Graph and version-chain endpoints are contract-stable** but currently
   backed by demo/stub implementations until runtime wiring is completed.

## Execution Modes

| `retrieval_mode` | `rerank.enabled` | `execution_mode`   |
|------------------|------------------|--------------------|
| `dense`          | `false`          | `dense`            |
| `dense`          | `true`           | `dense_rerank`     |
| `sparse`         | `false`          | `sparse`           |
| `sparse`         | `true`           | `sparse_rerank`    |
| `hybrid`         | `false`          | `hybrid`           |
| `hybrid`         | `true`           | `hybrid_rerank`    |

## Terminology

All field names, types, and shapes correspond to the backend service contracts:

- `RetrievalHit` — `src/backend/services/contracts.py`
- `AnswerContext` — `src/backend/services/contracts.py`
- `GraphContext` / `GraphNode` / `GraphEdge` — `src/backend/services/contracts.py`
- `RetrievalRequest` / `RerankConfig` / `LLMConfig` / `GraphConfig` — `src/backend/services/retrieval_modes.py`
- `SearchRequestModel` — `src/backend/app/schemas.py`
