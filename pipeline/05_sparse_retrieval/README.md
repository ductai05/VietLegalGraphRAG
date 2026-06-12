# Sparse Retrieval Pipeline

This stage builds Elasticsearch BM25 retrieval for VietLegalGraphRAG from the chunking output.

## Files

| File | Role |
|---|---|
| `scripts/prepare_sparse_data.py` | Join chunks with metadata, normalize fields, tokenize Vietnamese text and write `sparse_payload_v0.1.parquet` |
| `scripts/create_index.py` | Create the versioned Elasticsearch index from the mapping JSON |
| `scripts/ingest_chunks.py` | Bulk ingest sparse payload and update the stable alias |
| `scripts/run_pipeline_full.py` | Kaggle runner that starts Elasticsearch, builds data payload, creates index and ingests |

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



## Kaggle Runner

Attach two Kaggle input datasets:

- Source dataset containing `VietLegalGraphRAG/pipeline/05_sparse_retrieval`
- Chunking dataset containing `legal_chunking_dataset/chunks.parquet` and `legal_chunking_dataset/metadata.parquet`

Then install dependencies and run the scripts inside your Kaggle notebook cells.

### 1. Install Dependencies

You can automatically locate and install requirements using this cell:

```python
import glob
req_paths = glob.glob("/kaggle/input/**/05_sparse_retrieval/requirements.txt", recursive=True)
if req_paths:
    %pip install -r {req_paths[0]}
else:
    print("requirements.txt not found")
```

### 2. Run the Scripts

Choose one of the following runners depending on your task.

#### Option A: Full Pipeline (Elasticsearch Setup, Preparation, Indexing, and Ingest)

This script sets up local Elasticsearch, prepares the data payload, creates the index, and bulk ingests the documents:

```python
import glob
run_paths = glob.glob("/kaggle/input/**/05_sparse_retrieval/scripts/run_pipeline_full.py", recursive=True)
if run_paths:
    %run {run_paths[0]}
```

#### Option B: Tokenization Only

This script splits the chunks and prepares the tokenized payload splits. It is useful for dividing the processing workload:

```python
import glob
run_paths = glob.glob("/kaggle/input/**/05_sparse_retrieval/scripts/kaggle_tokenize_only.py", recursive=True)
if run_paths:
    %run {run_paths[0]}
```

#### Option C: Indexing Only

This script sets up Elasticsearch and ingests a pre-tokenized payload:

```python
import glob
run_paths = glob.glob("/kaggle/input/**/05_sparse_retrieval/scripts/kaggle_index_only.py", recursive=True)
if run_paths:
    %run {run_paths[0]}
```

### Environment Configuration

You must set the environment variables to specify the correct paths before running the scripts:

```python
%env SPARSE_DIR=/kaggle/input/vietlegalgraphrag-source/VietLegalGraphRAG/pipeline/05_sparse_retrieval
%env CHUNKS_PATH=/kaggle/input/vietnamese-legal-documents-cleaned/legal_chunking_dataset/chunks.parquet
%env METADATA_PATH=/kaggle/input/vietnamese-legal-documents-cleaned/legal_chunking_dataset/metadata.parquet
%env PAYLOAD_PATH=/kaggle/input/vietnamese-legal-documents-cleaned/sparse_payload_v0.1.parquet
%env RECREATE_INDEX=1
```

The Kaggle runner stores Elasticsearch data in `/kaggle/working/legal_sparse/es_data`.


