# Elasticsearch Vector Backend Design

## Goal

Use Elasticsearch as a supported dense retrieval backend and reduce initial
Elastic Cloud upload time without overwhelming a trial deployment.

## Current State

The corpus contains about 5.7 million normalized 1024-dimensional vectors in
575 float16 NumPy shards. The current Elasticsearch uploader converts every
vector to float32 JSON and sends batches of 100 documents sequentially. It
waits for each bulk request before producing the next request.

The current dense retriever supports Qdrant and FAISS only. Elasticsearch has
an ingest script, but no retrieval adapter, no full legal metadata mapping, and
no dependency declaration in the root requirements file.

## Ingest Architecture

`build_elasticsearch.py` will remain the single ingestion entry point. It will
process source shards in deterministic order and use Elasticsearch
`parallel_bulk` inside each shard. This permits concurrent network requests
while keeping shard-level checkpointing understandable and resumable.

Trial-safe defaults:

- 2 worker threads
- 500 documents per bulk request
- 20 MB maximum request size
- bounded producer queue
- retries with exponential backoff for HTTP 429, 502, 503, and 504

Users may increase worker and batch settings after benchmarking. The script
will report rows per second and failures so tuning is based on observed cluster
capacity.

The script will disable refresh during the initial load. Newly created indices
will use zero replicas during ingestion, then restore the requested replica
count and refresh interval after a successful full run. It will not restore
search settings after a partial or failed run because indexing is expected to
resume.

Each source shard is marked `done` only when every valid action from that shard
has succeeded. Failed documents stop the shard from being checkpointed. The
manifest will contain operational counts and index identity, but never
credentials.

Credentials may be provided through command-line arguments for compatibility,
or through `ELASTIC_CLOUD_ID` and `ELASTIC_API_KEY`. Environment variables are
the documented path.

## Elasticsearch Mapping

The index will store the dense vector plus the payload fields already defined
by the embedding pipeline. Fields used for exact filtering will use `keyword`,
integer range fields will use numeric mappings, and display text such as title
will remain searchable text with a keyword subfield where useful.

The vector field will remain an indexed 1024-dimensional cosine
`dense_vector`. Elasticsearch will build its approximate nearest-neighbor
index during ingestion. This work is CPU and memory intensive, so client-side
parallelism must remain bounded on a trial cluster.

`chunk_text` will not be added during this migration because existing payload
shards were built without it. Result expansion continues to use
`chunks.parquet`.

## Retrieval Architecture

`DenseRetriever` will accept exactly one of four targets:

- Qdrant local storage
- Qdrant URL
- FAISS directory
- Elasticsearch Cloud ID

Elasticsearch retrieval will use top-level approximate kNN search. The query
vector is produced by the existing encoder and query prefix. `num_candidates`
will be configurable, with a default derived from `top_k` and capped by the
Elasticsearch limit.

The existing filter contract will be preserved:

```json
{
  "effect_status": "Con hieu luc",
  "legal_type": ["Nghi dinh", "Thong tu"],
  "ranges": {
    "issuance_date_ts": {"gte": 20200101}
  }
}
```

Scalar values become `term` filters, lists become `terms` filters, and range
bounds become `range` filters. These are passed as kNN pre-filters. Search
responses exclude the vector field and are normalized to the same
`(score, payload)` contract used by the current retriever.

`evaluate_dense.py` will expose the same Elasticsearch target arguments so the
new backend can be evaluated through the existing Recall, MRR, and nDCG flow.

## Error Handling

The uploader will validate vector shape, finite values, payload/vector row
counts, source manifest status, and target index compatibility. Bulk failures
will be summarized without printing vector contents. Retryable HTTP statuses
will use bounded exponential backoff. Permanent mapping and validation errors
will fail the current shard and leave it eligible for resume.

The retriever will provide actionable errors for missing Elasticsearch client
dependencies, absent credentials, inaccessible indices, and incompatible
filters.

## Testing

Unit tests will cover:

- index mapping and ingest settings
- environment-variable credential resolution
- action generation and payload type preservation
- exact, list, and range filter translation
- Elasticsearch response normalization
- shard checkpoint behavior on success and failure
- target selection validation

Tests will use fake clients or patched helpers and will not contact Elastic
Cloud. A syntax/import verification pass will cover the modified CLI files.

## Documentation

The embedding README will document:

- installing the Elasticsearch Python client
- revoking exposed API keys and using environment variables
- trial-safe upload defaults
- a one-shard benchmark command
- gradual tuning of workers and batch size
- monitoring HTTP 429 responses
- Elasticsearch retrieval and evaluation commands

## Out of Scope

- Multiple uploader processes sharing one manifest
- Hybrid BM25 and dense score fusion
- Rebuilding embedding shards to include `chunk_text`
- Changing the embedding model or vector dimension
- Cluster-side resizing or Elastic Cloud billing changes
