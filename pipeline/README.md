# Pipeline Branch

This branch is for data processing only. Cloud upload and production import
belong in `develop/src/infra/scripts`.

## Stage Layout

```text
pipeline/
  01_eda/
    download/
    eda/
  02_preprocessing/
    clean/
    merge/
    chunk/
  03_embeddings/
    dense/
    sparse/
  04_graph/
  05_evaluation/
```

## Local Execution Pattern

Run code from the folder that owns the stage:

```bash
cd pipeline/01_eda/download
python download_data.py

cd ../../02_preprocessing/merge
python merge_clean_dataset.py

cd ../chunk
python batch_chunk.py --help

cd ../../03_embeddings/dense/scripts
python prepare_embedding_data.py --help
python embed_shards.py --help

cd ../../sparse/scripts
python prepare_sparse_data.py --help

cd ../../../04_graph/scripts
python run_graph_construction.py --help

cd ../../05_evaluation
python evaluate_dense.py --help
python evaluate_sparse.py --help
```

The scripts use local `sys.path` setup for sibling `src` folders where needed.
They do not require installing `pipeline` as a global package.
