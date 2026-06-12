# Dense Retrieval Pipeline - Current Status

**Last updated:** 2026-06-12
**Scope:** `pipeline/04_embedding` dense retrieval path for VietLegalGraphRAG

## 1. Current working state

The pipeline is runnable end-to-end for dense retrieval evaluation:

```bash
python pipeline/07_evaluation/evaluate_dense.py \
  --gold pipeline/07_evaluation/eval_questions_gold.jsonl \
  --url http://129.212.184.109:8333/ \
  --chunks data/preprocessed/chunking/chunks.parquet \
  --top-k 10 \
  --output data/legal_embedding/dense_qdrant_eval_results.json
```

Observed result on the current setup:

```json
{
  "queries": 200,
  "recall@10": 0.5575,
  "mrr@10": 0.3997936507936508,
  "ndcg@10": 0.4336201997893766
}
```

## 2. What is already implemented

- `prepare_embedding_data.py`
  - Freezes the embedding payload from `chunks.parquet` + `metadata.parquet`
  - Rebuilds `contextual_text`
  - Enforces invariants and emits repair candidates
- `embed_shards.py`
  - Encodes documents into shard outputs
  - Supports resume via shard `manifest.json`
- `build_qdrant.py`
  - Creates Qdrant collection `legal_chunks_dense_v1`
  - Upserts completed shards
  - Creates payload indexes for key legal metadata fields
- `dense_retrieval.py`
  - Encodes queries with the same encoder used for indexing
  - Uses the query prefix defined in `embedding_common.py`
  - Supports Qdrant and compact FAISS member indexes
  - Supports metadata filters and optional context expansion
- `pipeline/07_evaluation/evaluate_dense.py`
  - Computes `Recall@K`, `MRR@K`, `nDCG@K`
  - Matches gold by `chunk_id` or `doc_id`
  - Supports optional reranking over a larger dense candidate pool
- `rerank.py`
  - Provides `BaseReranker`, `BGEReranker`, and `QwenReranker`
  - Formats metadata-aware passage text for cross-encoder scoring
  - Falls back to dense order if reranker initialization or scoring fails

## 3. Current retrieval configuration

- Model: `darklethelong/vnlegal-lal`
- Vector size: `1024`
- Similarity: cosine
- Collection name: `legal_chunks_dense_v1`
- Query prefix:
  - `Instruct: Given a Vietnamese legal question, retrieve relevant legal passages that answer the question`
  - `Query: ...`
- Query max length in retrieval: `512`
- Search path used in evaluation: single-stage dense retrieval against Qdrant

## 4. Storage and artifacts

Typical artifacts currently produced by the pipeline:

- `embed_payload_v0.1.parquet`
- `prepare_manifest.json`
- shard directories from `embed_shards.py`
- `qdrant_manifest.json`
- evaluation output JSON from `pipeline/07_evaluation/evaluate_dense.py`

The retrieval code can also fall back to FAISS member shards when Qdrant is not used.

## 5. What the current numbers imply

- `Recall@10 = 0.5575`
  - The correct chunk/doc is often not in the first 10 dense hits.
- `MRR@10 = 0.3998`
  - When the answer is retrieved, the rank is still not consistently near the top.
- `nDCG@10 = 0.4336`
  - Ranking quality inside the top 10 is still weak relative to the gold set.

## 6. Likely bottlenecks to investigate next

- Query representation may be too weak for legal question matching.
- Indexing granularity may be mismatched with the gold relevance labels.
- Single-stage dense retrieval may still benefit from hybrid retrieval, but reranking is already implemented.
- BM25 is not implemented in the current pipeline, so lexical retrieval is not yet available as a baseline or hybrid signal.
- Metadata filters and context expansion may not be enough to recover hard cases.
- `max_length=512` for queries may truncate useful legal intent.
- The current evaluation uses `expand=False`, so retrieval quality is measured before any optional context expansion.

## 7. Relevant files

- `prepare_embedding_data.py`
- `embed_shards.py`
- `build_qdrant.py`
- `dense_retrieval.py`
- `pipeline/07_evaluation/evaluate_dense.py`
- `embedding_common.py`

