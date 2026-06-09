# Sau `KAGGLE_MEMBER.py` — chạy trên Kaggle (người merge)

Add dataset:

- `brdh7940/04-embedding`
- `cieldt/vietlegalgraphrag-legalembedding-member3`

---

**Cell 1 — tải output 4 member**

```python
!kaggle kernels output brdh7940/4-embedding -p /kaggle/working/member1
!kaggle kernels output dinhducanhkhoa/chunking-2 -p /kaggle/working/member2
!kaggle kernels output nguyentrantrungkien/member4 -p /kaggle/working/member4
!kaggle kernels output nguynlhongtrung/embedding -p /kaggle/working/member5
!rm -rf /kaggle/working/member*/legal_embedding/.cache
```

---

**Cell 2 — verify + merge**

```python
%run /kaggle/input/datasets/brdh7940/04-embedding/04_embedding/KAGGLE_MERGE.py
```

Pass: in `Member shard verification PASSED` rồi `Merge complete`.

Output: `/kaggle/working/legal_embedding/data/shards/`

---

**Cell 3 — publish merged shards**

Save Version → Output tab → publish `/kaggle/working/legal_embedding/data/shards/` lên Kaggle Dataset.

---

**Máy local — build Qdrant**

```bash
cd pipeline/04_embedding
pip install -r requirements.txt

python build_qdrant.py \
  --shards-dir /path/to/shards \
  --url http://localhost:6333 \
  --recreate
```

```bash
python dense_retrieval.py \
  --url http://localhost:6333 \
  --chunks /path/to/chunks.parquet \
  --query "Điều kiện cấp giấy phép xây dựng là gì?" \
  --top-k 5
```
