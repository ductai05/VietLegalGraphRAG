# Dense Retrieval Hand-off

## Current status

- All five members finished `KAGGLE_MEMBER.py`.
- The embedding owner is running `KAGGLE_MERGE.py` on Kaggle.
- Model/config are frozen: `darklethelong/vnlegal-lal`, 1024 dimensions,
  cosine similarity, normalized vectors, document `max_length=1024`.
- Query encoding must use the prefix already implemented in
  `dense_retrieval.py`. Never add that prefix to indexed documents.

`KAGGLE_MERGE.py` does not copy the roughly 30 GB of member vectors. It verifies
the five read-only datasets, ignores duplicate chunk IDs, repairs missing
chunks, and builds compact deduplicated FAISS indexes.

## Artifacts to hand over

Keep these artifacts together. The original member shards are the portable
source of truth and are required to build Qdrant later.

```text
faiss_members/                 # compact Kaggle retrieval artifact
member_inputs/
  shards_member_1/ ... shards_member_5/  # original vectors + payload shards
  embed_payload_v0.1.parquet             # canonical chunk-ID set
repair_shards/                 # optional Kaggle repair output
chunks.parquet                 # text lookup and context expansion
metadata.parquet
pipeline/04_embedding/
```

Publish `/kaggle/working/legal_embedding/faiss_members/`. Also record the final
`unique_rows`, `duplicates_removed`, and repair summary from its
`manifest.json`.

## FAISS acceptance check

Every fresh environment must install the pipeline dependencies. `faiss-cpu` is the
package name, while `faiss` is its Python import name:

```bash
cd pipeline/04_embedding
python -m pip install -r requirements.txt
python -c "import faiss; print(faiss.__version__)"
python dense_retrieval.py \
  --faiss-dir /data/legal_embedding/faiss_members \
  --chunks /data/legal_chunking_dataset/chunks.parquet \
  --query "Điều kiện cấp giấy phép xây dựng là gì?" \
  --top-k 5
```

FAISS is the portable fallback and local evaluation target. Its metadata
filters are post-filters, so increase `--faiss-oversample` for selective
filters. Do not delete the member shards after publishing FAISS.

## Build Qdrant on the server

Qdrant is the recommended shared service for LLM and evaluation work because
it supports server-side payload filters. Do not build the full collection in
Kaggle: member vectors, canonical shards, and Qdrant storage can exceed its
disk limit.

The server needs the five member datasets, `chunks.parquet`, `metadata.parquet`,
the embedding pipeline, a GPU if missing chunks still need repair, and enough
free disk for both canonical shards and Qdrant storage. Put all five
`shards_member_*` directories under
`/data/legal_embedding/member_inputs/`. Use a persistent Qdrant server, for
example at `http://localhost:6333`.

First create one deduplicated, complete, Qdrant-ready shard directory:

```bash
cd pipeline/04_embedding
python -m pip install -r requirements.txt

# Rebuild the canonical payload if it was not included in the hand-off.
python prepare_embedding_data.py \
  --chunks /data/legal_chunking_dataset/chunks.parquet \
  --metadata /data/legal_chunking_dataset/metadata.parquet \
  --output-dir /data/legal_embedding/member_inputs \
  --version v0.1 \
  --chunker-version v0.1

python repair_member_shards.py \
  --search-root /data/legal_embedding/member_inputs \
  --output-dir /data/legal_embedding/canonical_shards \
  --work-dir /data/legal_embedding/repair_work
```

Then create and populate the Qdrant collection:

```bash
python build_qdrant.py \
  --shards-dir /data/legal_embedding/canonical_shards \
  --url http://localhost:6333 \
  --collection legal_chunks_dense_v1 \
  --recreate
```

Use `--api-key "$QDRANT_API_KEY"` when required. Use `--recreate` only for the
first clean build; rerunning without it resumes from
`canonical_shards/qdrant_manifest.json`. The build fails if the final Qdrant
point count differs from the canonical row count.

Qdrant payloads intentionally omit `chunk_text` to control storage size.
Consumers must pass `chunks.parquet` to retrieval so returned chunk IDs can be
resolved to text and expanded context.

## Qdrant acceptance check

```bash
python dense_retrieval.py \
  --url http://localhost:6333 \
  --collection legal_chunks_dense_v1 \
  --chunks /data/legal_chunking_dataset/chunks.parquet \
  --query "Điều kiện cấp giấy phép xây dựng là gì?" \
  --filters '{"effect_status":"Còn hiệu lực"}' \
  --top-k 5
```

Each hit follows this contract:

```json
{
  "chunk_id": "...",
  "dense_score": 0.81,
  "payload": {},
  "citation": "...",
  "optional_expanded_context": "..."
}
```

The LLM owner should use `payload.chunk_text` when present, otherwise the text
resolved from `chunks.parquet`, and prefer `optional_expanded_context` when it
is returned. Preserve `citation` in generated answers.

## Evaluation owner

Create a UTF-8 JSONL gold set with `query`, optional `group`, relevant chunk or
document IDs, and optional filters. Evaluate either Qdrant or FAISS:

```bash
python evaluate_dense.py \
  --gold /data/evaluation/dense_gold.jsonl \
  --url http://localhost:6333 \
  --chunks /data/legal_chunking_dataset/chunks.parquet \
  --top-k 10 \
  --output /data/evaluation/dense_qdrant_eval.json
```

Report Recall@10, MRR@10, and nDCG@10 overall and by group. Compare Qdrant
against FAISS by replacing `--url` with `--faiss-dir`; a large gap requires
checking FAISS `nprobe`/oversampling or Qdrant indexing before LLM evaluation.
