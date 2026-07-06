# Sparse Retrieval Pipeline

This stage builds Elasticsearch BM25 retrieval for VietLegalGraphRAG from the chunking output.

## Files

| File | Role |
|---|---|
| `scripts/prepare_sparse_data.py` | Join chunks with metadata, normalize fields, tokenize Vietnamese text and write `sparse_payload_v0.1.parquet` |
| `scripts/merge_sparse_data.py` | Merge multiple split sparse payload parquet files into a single payload |
| `scripts/cloud_index.py` | Index and upload sparse payload to an Elasticsearch cluster (e.g., Elastic Cloud) |
| `scripts/data_tokenize.py` | Kaggle runner that splits the chunks and prepares the tokenized payload splits |

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

Upload to Elasticsearch (e.g. Elastic Cloud):

```bash
python scripts/cloud_index.py \
  --url https://your-elastic-endpoint:443 \
  --api-key your-api-key \
  --payload /path/to/legal_sparse/data/sparse_payload_v0.1.parquet \
  --mapping mappings/vietlegal_chunks_sparse_v1.json
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

#### Tokenization Only

This script splits the chunks and prepares the tokenized payload splits. It is useful for dividing the processing workload:

```python
import glob
run_paths = glob.glob("/kaggle/input/**/05_sparse_retrieval/scripts/data_tokenize.py", recursive=True)
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
```
