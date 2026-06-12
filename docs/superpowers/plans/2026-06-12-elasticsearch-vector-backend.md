# Elasticsearch Vector Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Elasticsearch as a complete dense retrieval backend and make Elastic Cloud shard ingestion faster with bounded parallel bulk requests that remain safe for a trial cluster.

**Architecture:** Put Elasticsearch-specific data translation in a lightweight `elasticsearch_common.py` module so mapping, credentials, filters, actions, and response normalization can be unit tested without loading the embedding model. Keep source shards sequential for deterministic resume, but use `parallel_bulk` inside each shard with a bounded queue and retries. Extend the existing `DenseRetriever` and evaluation CLI rather than creating a second retrieval contract.

**Tech Stack:** Python 3.14, NumPy, Polars, Elasticsearch Python client, standard-library `unittest`, existing transformer encoder.

---

## File Structure

- Create `pipeline/04_embedding/elasticsearch_common.py`: pure Elasticsearch mapping, credential, filter, ingest-action, and response helpers.
- Modify `pipeline/04_embedding/build_elasticsearch.py`: trial-safe CLI, bounded `parallel_bulk`, progress metrics, shard checkpointing, and index lifecycle settings.
- Modify `pipeline/04_embedding/dense_retrieval.py`: optional Elasticsearch client and kNN search backend.
- Modify `pipeline/07_evaluation/evaluate_dense.py`: Elasticsearch target arguments forwarded to `DenseRetriever`.
- Modify `pipeline/04_embedding/README.md`: upload tuning, security, retrieval, and evaluation commands.
- Modify `requirements.txt`: declare the Elasticsearch Python client.
- Create `tests/test_elasticsearch_common.py`: pure helper behavior.
- Create `tests/test_elasticsearch_ingest.py`: parallel bulk and checkpoint behavior using fakes.
- Create `tests/test_elasticsearch_retrieval.py`: target selection and response normalization using fakes.

### Task 1: Elasticsearch Common Contract

**Files:**
- Create: `tests/test_elasticsearch_common.py`
- Create: `pipeline/04_embedding/elasticsearch_common.py`

- [ ] **Step 1: Write failing tests for credentials, mapping, action generation, filters, and hit normalization**

```python
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

EMBEDDING_DIR = Path(__file__).resolve().parents[1] / "pipeline" / "04_embedding"
sys.path.insert(0, str(EMBEDDING_DIR))

from elasticsearch_common import (
    build_elasticsearch_filter,
    build_index_definition,
    make_index_action,
    normalize_search_hits,
    resolve_credentials,
)


class ElasticsearchCommonTests(unittest.TestCase):
    def test_resolve_credentials_prefers_explicit_values(self):
        with patch.dict(os.environ, {"ELASTIC_CLOUD_ID": "env-id", "ELASTIC_API_KEY": "env-key"}):
            self.assertEqual(resolve_credentials("arg-id", "arg-key"), ("arg-id", "arg-key"))

    def test_resolve_credentials_reads_environment(self):
        with patch.dict(os.environ, {"ELASTIC_CLOUD_ID": "env-id", "ELASTIC_API_KEY": "env-key"}):
            self.assertEqual(resolve_credentials(None, None), ("env-id", "env-key"))

    def test_mapping_contains_vector_and_legal_filter_fields(self):
        definition = build_index_definition(number_of_shards=1)
        props = definition["mappings"]["properties"]
        self.assertEqual(props["vector"]["dims"], 1024)
        self.assertEqual(props["issuance_date_ts"]["type"], "long")
        self.assertEqual(props["effect_status"]["type"], "keyword")
        self.assertEqual(definition["settings"]["index"]["refresh_interval"], "-1")

    def test_make_action_preserves_numeric_ranges_and_omits_nulls(self):
        row = {"chunk_id": "c1", "doc_id": 10000174386, "issuance_date_ts": 20200101, "effect_date_ts": None}
        action = make_index_action("legal", row, np.zeros(1024, dtype=np.float16))
        self.assertEqual(action["_source"]["doc_id"], "10000174386")
        self.assertEqual(action["_source"]["issuance_date_ts"], 20200101)
        self.assertNotIn("effect_date_ts", action["_source"])

    def test_build_filter_translates_exact_list_and_range_conditions(self):
        result = build_elasticsearch_filter({
            "effect_status": "Con hieu luc",
            "legal_type": ["Nghi dinh", "Thong tu"],
            "ranges": {"issuance_date_ts": {"gte": 20200101}},
        })
        self.assertEqual(result, [
            {"term": {"effect_status": "Con hieu luc"}},
            {"terms": {"legal_type": ["Nghi dinh", "Thong tu"]}},
            {"range": {"issuance_date_ts": {"gte": 20200101}}},
        ])

    def test_normalize_search_hits_removes_vector(self):
        hits = [{"_score": 0.9, "_source": {"chunk_id": "c1", "vector": [1.0]}}]
        self.assertEqual(normalize_search_hits(hits), [(0.9, {"chunk_id": "c1"})])
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_elasticsearch_common -v`

Expected: import failure because `elasticsearch_common` does not exist.

- [ ] **Step 3: Implement the pure Elasticsearch contract**

Implement these public functions in `pipeline/04_embedding/elasticsearch_common.py`:

```python
def resolve_credentials(cloud_id: str | None, api_key: str | None) -> tuple[str, str]: ...
def build_index_definition(number_of_shards: int, number_of_replicas: int = 0) -> dict[str, Any]: ...
def make_index_action(index: str, row: dict[str, Any], vector: np.ndarray) -> dict[str, Any]: ...
def build_elasticsearch_filter(filters: dict[str, Any] | None) -> list[dict[str, Any]]: ...
def normalize_search_hits(hits: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]: ...
def resolve_num_candidates(top_k: int, configured: int | None) -> int: ...
```

Use `PAYLOAD_FIELDS`, `VECTOR_SIZE`, and `stable_point_id` from `embedding_common`. Map identifiers and categorical metadata to `keyword`, date timestamps and `doc_id` lookup-safe fields to their intended types, and reject malformed vectors before serialization.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m unittest tests.test_elasticsearch_common -v`

Expected: all common-contract tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add pipeline/04_embedding/elasticsearch_common.py tests/test_elasticsearch_common.py
git commit -m "feat: add elasticsearch backend contract"
```

### Task 2: Trial-Safe Parallel Ingestion

**Files:**
- Create: `tests/test_elasticsearch_ingest.py`
- Modify: `pipeline/04_embedding/build_elasticsearch.py`

- [ ] **Step 1: Write failing tests for parallel bulk configuration and checkpoint behavior**

Create tests that call an extracted `upload_shard` function with a fake `parallel_bulk` iterator. Verify:

```python
result = upload_shard(
    es=fake_es,
    index="legal",
    payload_df=fake_payload,
    vectors=fake_vectors,
    workers=2,
    batch_size=500,
    max_chunk_bytes=20 * 1024 * 1024,
    queue_size=2,
    parallel_bulk_fn=fake_parallel_bulk,
)
self.assertEqual(result.uploaded, 2)
self.assertEqual(captured["thread_count"], 2)
self.assertEqual(captured["chunk_size"], 500)
```

Add a failure case where one bulk item returns `False`; assert `upload_shard` raises and the caller does not write a `done` manifest entry.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_elasticsearch_ingest -v`

Expected: failure because `upload_shard` and the new CLI settings do not exist.

- [ ] **Step 3: Implement bounded parallel ingestion**

Refactor `build_elasticsearch.py` to:

- resolve credentials from arguments or environment;
- add `--workers` default `2`, `--upsert-batch` default `500`, `--max-chunk-mb` default `20`, `--queue-size` default `2`, `--number-of-shards` default `1`, `--final-replicas` default `0`, and `--final-refresh-interval` default `5s`;
- stream actions from shard rows instead of accumulating separate 100-item lists;
- consume `helpers.parallel_bulk(...)` with `thread_count`, `chunk_size`, `max_chunk_bytes`, `queue_size`, `max_retries=5`, `initial_backoff=2`, `max_backoff=60`, and retry statuses `(429, 502, 503, 504)`;
- summarize failures without vector data;
- checkpoint only after zero failed actions;
- log elapsed seconds and rows per second per shard;
- validate an existing index mapping before resuming;
- finalize refresh and replica settings only after every selected source shard is complete.

Keep explicit deterministic `_id` values because resume and duplicate avoidance are required, despite the indexing cost compared with auto-generated IDs.

- [ ] **Step 4: Run ingestion tests and verify GREEN**

Run: `python -m unittest tests.test_elasticsearch_ingest -v`

Expected: all ingest tests pass.

- [ ] **Step 5: Verify CLI help without credentials**

Run: `python pipeline/04_embedding/build_elasticsearch.py --help`

Expected: exits 0 and displays the new worker, batch, queue, and environment-variable options.

- [ ] **Step 6: Commit Task 2**

```powershell
git add pipeline/04_embedding/build_elasticsearch.py tests/test_elasticsearch_ingest.py
git commit -m "feat: parallelize elasticsearch shard ingestion"
```

### Task 3: Elasticsearch Dense Retrieval and Evaluation

**Files:**
- Create: `tests/test_elasticsearch_retrieval.py`
- Modify: `pipeline/04_embedding/dense_retrieval.py`
- Modify: `pipeline/07_evaluation/evaluate_dense.py`

- [ ] **Step 1: Write failing tests for target selection and kNN requests**

Test a fake Elasticsearch client with:

```python
client.search.return_value = {
    "hits": {"hits": [{"_score": 0.87, "_source": {"chunk_id": "c1", "doc_id": "42"}}]}
}
points = retriever._search_elasticsearch(vector, filters, top_k=5)
self.assertEqual(points, [(0.87, {"chunk_id": "c1", "doc_id": "42"})])
request = client.search.call_args.kwargs
self.assertEqual(request["knn"]["field"], "vector")
self.assertEqual(request["knn"]["k"], 5)
self.assertNotIn("vector", request["source_excludes"])
```

Also verify the constructor rejects zero or multiple targets and accepts an Elasticsearch target without initializing Qdrant.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_elasticsearch_retrieval -v`

Expected: failure because the Elasticsearch target and search method do not exist.

- [ ] **Step 3: Implement Elasticsearch retrieval**

Update `DenseRetriever` to accept `elastic_cloud_id`, `elastic_api_key`, `elastic_index`, and `elastic_num_candidates`. Import Elasticsearch optionally with an actionable dependency error. Route search to `_search_elasticsearch` when configured.

Build a top-level kNN request containing:

```python
knn = {
    "field": "vector",
    "query_vector": vector.astype(np.float32).tolist(),
    "k": top_k,
    "num_candidates": resolve_num_candidates(top_k, self.elastic_num_candidates),
}
```

Attach translated filters when present, request only payload fields, exclude `vector`, and normalize hits through `elasticsearch_common`.

Add CLI flags `--elastic-cloud-id`, `--elastic-index`, `--elastic-api-key`, and `--elastic-num-candidates`. Use environment credentials when explicit values are absent.

- [ ] **Step 4: Forward Elasticsearch arguments through evaluation**

Add the same target and tuning arguments to `evaluate_dense.py`, then pass them into `DenseRetriever`. Update the reranker warning to mention Elasticsearch payloads.

- [ ] **Step 5: Run retrieval tests and verify GREEN**

Run: `python -m unittest tests.test_elasticsearch_retrieval -v`

Expected: all retrieval tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add pipeline/04_embedding/dense_retrieval.py pipeline/07_evaluation/evaluate_dense.py tests/test_elasticsearch_retrieval.py
git commit -m "feat: query elasticsearch dense vectors"
```

### Task 4: Dependencies, Documentation, and Full Verification

**Files:**
- Modify: `requirements.txt`
- Modify: `pipeline/04_embedding/README.md`

- [ ] **Step 1: Declare the supported client dependency**

Add:

```text
elasticsearch>=8.16.0,<10
```

- [ ] **Step 2: Document secure trial upload and tuning**

Document revoking the exposed API key, using `ELASTIC_CLOUD_ID` and `ELASTIC_API_KEY`, benchmarking one shard first, starting with `2` workers and `500` documents, watching for HTTP 429, and increasing only one parameter at a time.

Include this production command without literal credentials:

```powershell
$env:ELASTIC_CLOUD_ID="your-deployment-cloud-id"
$env:ELASTIC_API_KEY="your-new-api-key"
python pipeline/04_embedding/build_elasticsearch.py `
  --shards-dir "data/embedding/shards" `
  --index "legal_chunks_dense_v1" `
  --recreate `
  --workers 2 `
  --upsert-batch 500 `
  --max-chunk-mb 20
```

Document Elasticsearch retrieval and evaluation commands using environment credentials.

- [ ] **Step 3: Run the complete unit suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass with no Elastic Cloud calls.

- [ ] **Step 4: Run syntax verification**

Run:

```powershell
python -m py_compile pipeline/04_embedding/elasticsearch_common.py pipeline/04_embedding/build_elasticsearch.py pipeline/04_embedding/dense_retrieval.py pipeline/07_evaluation/evaluate_dense.py
```

Expected: exits 0.

- [ ] **Step 5: Run CLI smoke checks**

Run:

```powershell
python pipeline/04_embedding/build_elasticsearch.py --help
python pipeline/04_embedding/dense_retrieval.py --help
python pipeline/07_evaluation/evaluate_dense.py --help
```

Expected: each exits 0 and exposes Elasticsearch arguments.

- [ ] **Step 6: Inspect the final diff and secret scan**

Run:

```powershell
git diff --check
rg -n "MnlFc3|ml-lawbot:|ELASTIC_API_KEY=.*[A-Za-z0-9+/]{20}" . -g '!output/**' -g '!data/**'
git status --short
```

Expected: no whitespace errors, no exposed credential copied into tracked files, and only intended files plus the user's existing dirty output file.

- [ ] **Step 7: Commit Task 4**

```powershell
git add requirements.txt pipeline/04_embedding/README.md
git commit -m "docs: add elasticsearch ingestion workflow"
```
