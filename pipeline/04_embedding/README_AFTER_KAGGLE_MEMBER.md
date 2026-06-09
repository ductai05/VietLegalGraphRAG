# After `KAGGLE_MEMBER.py`: compact Kaggle retrieval artifact

Add the five member datasets, the `04-embedding` dataset, and
`vietnamese-legal-documents-cleaned` as notebook inputs. Do not download or
copy the member datasets into `/kaggle/working`.

Run:

```python
%run /kaggle/input/datasets/brdh7940/04-embedding/04_embedding/KAGGLE_MERGE.py
```

Despite its legacy name, `KAGGLE_MERGE.py` does not physically merge the
roughly 30 GB of member vectors. It:

1. scans the five read-only member datasets;
2. encodes only missing chunk IDs into `data/repair_shards`;
3. trains one shared IVF-PQ codebook;
4. writes five compact FAISS indexes plus an optional repair index.

Publish only:

```text
/kaggle/working/legal_embedding/faiss_members/
```

Smoke test:

```bash
python dense_retrieval.py \
  --faiss-dir /kaggle/working/legal_embedding/faiss_members \
  --chunks /kaggle/input/datasets/brdh7940/vietnamese-legal-documents-cleaned/legal_chunking_dataset/chunks.parquet \
  --query "Điều kiện cấp giấy phép xây dựng là gì?" \
  --top-k 5
```

FAISS filters are applied after ANN retrieval. Increase `--faiss-oversample`
for highly selective filters. Keep the five original member datasets as the
portable source vectors; Qdrant remains an optional deployment target outside
the Kaggle disk constraint.
