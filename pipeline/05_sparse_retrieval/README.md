# Sparse Retrieval Pipeline

This stage builds Elasticsearch BM25 retrieval for VietLegalGraphRAG from the chunking output.

## Files

| File | Role |
|---|---|
| `scripts/prepare_sparse_data.py` | Join chunks with metadata, normalize fields, tokenize Vietnamese text and write `sparse_payload_v0.1.parquet` |
| `scripts/create_index.py` | Create the versioned Elasticsearch index from the mapping JSON |
| `scripts/ingest_chunks.py` | Bulk ingest sparse payload and update the stable alias |
| `src/sparse_retriever.py` | Query router, BM25 DSL, exact document-number search and output formatting |
| `scripts/smoke_test.py` | Run JSONL smoke queries |
| `scripts/evaluate_sparse.py` | Compute Recall, MRR and nDCG from a small gold set |
| `scripts/kaggle_elasticsearch_single_cell.py` | Kaggle runner that starts Elasticsearch and Cloudflare Tunnel |

## Data Contract

Input:

```text
legal_chunking_dataset/
  chunks.parquet
  metadata.parquet
```

The pipeline filters `chunks.keyword_index=True`, joins `chunks.doc_id = metadata.id`, keeps `chunk_id` as the Elasticsearch `_id`, and creates:

```text
legal_sparse/data/
  sparse_base_v0.1.parquet
  sparse_payload_v0.1.parquet
  sparse_payload_v0.1.ndjson
  prepare_sparse_manifest.json
```

## Local Usage

Install dependencies from this directory:

```bash
pip install -r requirements.txt
```

Prepare payload:

```bash
python scripts/prepare_sparse_data.py \
  --chunks /path/to/chunks.parquet \
  --metadata /path/to/metadata.parquet \
  --output-dir /path/to/legal_sparse/data \
  --version v0.1 \
  --export-ndjson
```

Create index:

```bash
python scripts/create_index.py \
  --url http://127.0.0.1:9200 \
  --index vietlegal_chunks_sparse_v1 \
  --mapping mappings/vietlegal_chunks_sparse_v1.json
```

Ingest:

```bash
python scripts/ingest_chunks.py \
  --url http://127.0.0.1:9200 \
  --payload /path/to/legal_sparse/data/sparse_payload_v0.1.parquet \
  --index vietlegal_chunks_sparse_v1 \
  --alias vietlegal_chunks_sparse_current \
  --batch-size 1000 \
  --refresh
```

Query:

```bash
python -m src.sparse_retriever \
  --url http://127.0.0.1:9200 \
  --query "điều kiện hưởng bảo hiểm xã hội" \
  --top-k 5
```

With metadata filter:

```bash
python -m src.sparse_retriever \
  --url http://127.0.0.1:9200 \
  --query "cấp giấy phép xây dựng" \
  --filters '{"effect_status":"Còn hiệu lực","ranges":{"issuance_date":{"gte":"2020-01-01"}}}' \
  --top-k 5
```

## Output Format

Each hit follows the sparse contract:

```json
{
  "chunk_id": "...",
  "score": 12.34,
  "retriever": "sparse",
  "rank": 1,
  "payload": {},
  "citation": "...",
  "optional_expanded_context": null
}
```

`table_summary`, `procedure_record` and `clause_group` can expand context from `raw_table_id` or `parent_id` when `expand=True`.

## Kaggle Runner

Attach two Kaggle input datasets:

- Source dataset containing `VietLegalGraphRAG/pipeline/05_sparse_retrieval`
- Chunking dataset containing `legal_chunking_dataset/chunks.parquet` and `legal_chunking_dataset/metadata.parquet`

Then run one notebook cell:

```python
%run /kaggle/input/vietlegalgraphrag-source/VietLegalGraphRAG/pipeline/05_sparse_retrieval/scripts/kaggle_elasticsearch_single_cell.py
```

If your dataset slugs are different, set paths before `%run`:

```python
%env SPARSE_DIR=/kaggle/input/vietlegalgraphrag-source/VietLegalGraphRAG/pipeline/05_sparse_retrieval
%env CHUNKS_PATH=/kaggle/input/vietnamese-legal-documents-cleaned/legal_chunking_dataset/chunks.parquet
%env METADATA_PATH=/kaggle/input/vietnamese-legal-documents-cleaned/legal_chunking_dataset/metadata.parquet
%env RECREATE_INDEX=1
%run /kaggle/input/vietlegalgraphrag-source/VietLegalGraphRAG/pipeline/05_sparse_retrieval/scripts/kaggle_elasticsearch_single_cell.py
```

The runner performs these steps in order:

1. Install Python dependencies.
2. Locate source, chunks and metadata paths.
3. Download and start Elasticsearch.
4. Start Cloudflare Tunnel.
5. Prepare `sparse_payload_v0.1.parquet` and `.ndjson`.
6. Create or recreate `vietlegal_chunks_sparse_v1`.
7. Bulk ingest payload and point `vietlegal_chunks_sparse_current` to the index.
8. Keep the notebook cell alive so Elasticsearch and the tunnel remain available.

Environment variables can override paths, index names and runtime settings. See `config.example.env`.

The Kaggle runner stores Elasticsearch data in `/kaggle/working/legal_sparse/es_data` and prints the Cloudflare public URL when detected.

## Smoke and Evaluation

Smoke:

```bash
python scripts/smoke_test.py \
  --queries eval/smoke_queries.jsonl \
  --url http://127.0.0.1:9200 \
  --top-k 5
```

Evaluation:

```bash
python scripts/evaluate_sparse.py \
  --gold eval/smoke_queries.jsonl \
  --url http://127.0.0.1:9200 \
  --top-k 10 \
  --output /path/to/legal_sparse/logs/sparse_eval.json
```

Fill `expected_doc_ids` or `expected_chunk_ids` in the JSONL file before treating metrics as a real baseline.
