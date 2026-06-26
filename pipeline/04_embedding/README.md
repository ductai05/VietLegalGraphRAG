# Dense Embedding Pipeline

> MVP update 2026-06-26: Qdrant ingestion scripts were removed from the active
> code path. Dense retrieval for the demo uses Elasticsearch as the serving
> backend. Older Qdrant notes below are historical and should not be used for
> MVP setup.

Pipeline này hiện thực kế hoạch trong `PLAN_EMBEDDING.md` cho model
`darklethelong/vnlegal-lal`:

1. Lọc `embed=True`, loại `raw_table` và `hard_char_split`.
2. Join metadata, rebuild `contextual_text`, chuẩn hóa ngày.
3. Encode theo shard float16, có manifest để resume.
4. Upsert shard vào Elasticsearch dense index.
5. Dense retrieval, expansion và đánh giá Recall/MRR/nDCG.

## Các file

| File | Vai trò |
|---|---|
| `prepare_embedding_data.py` | Freeze `embed_payload_v0.1.parquet`, kiểm tra invariant và xuất danh sách bảng cần repair |
| `embed_shards.py` | Encode document theo shard, checkpoint bằng `manifest.json` |
| `dense_retrieval.py` | Query prefix, filter, citation và expansion từ `chunks.parquet` |
| `manage_shards.py` | CLI quản lý shard (verify, merge shards/faiss, repair) |
| `embedding_common.py` | Hằng số và utility dùng chung |
| `pipeline/07_evaluation/evaluate_dense.py` | Tính Recall@K, MRR@K, nDCG@K từ gold JSONL |

## 1. Chuẩn bị Kaggle

Bật GPU và Internet trong Notebook. Thêm dataset chunking có:

```text
/kaggle/input/<dataset>/
  chunks.parquet
  metadata.parquet
```

Đưa thư mục `04_embedding` lên Kaggle Dataset hoặc clone repo. Trên Kaggle,
`/kaggle/input` là read-only nhưng vẫn chạy script được; mọi output phải ghi vào
`/kaggle/working`.

### 1.1. Sửa PyTorch cho P100 trước

Kiểm tra GPU và CUDA architecture có trong wheel hiện tại:

```python
import torch
print(torch.__version__, torch.cuda.get_device_name(0), torch.cuda.get_arch_list())
```

Nếu output là `torch 2.10.0+cu128`, GPU **Tesla P100**, và danh sách không có
`sm_60`, thay wheel CUDA 12.8 bằng wheel CUDA 12.6 của cùng phiên bản:

```bash
!pip install --force-reinstall --no-cache-dir torch==2.10.0 \
  --index-url https://download.pytorch.org/whl/cu126
```

Sau khi cài xong, dùng menu **Session > Restart Session**, rồi chạy lại cell kiểm
tra. Không tiếp tục nếu version vẫn là `+cu128` hoặc `sm_60` chưa xuất hiện.
Không dùng `pip install -U torch` trên P100. Với T4 (`sm_75`), giữ wheel Kaggle
mặc định nếu `torch.cuda.get_arch_list()` có `sm_75`.

### 1.2. Cài dependency pipeline sau khi restart

```bash
%cd /kaggle/input/datasets/brdh7940/04-embedding/04_embedding
!python -m pip install -q -r requirements.txt
!python -c "import faiss, polars, pyarrow, elasticsearch, transformers; print('embedding dependencies OK')"
```

Luôn dùng `python -m pip` để cài vào đúng interpreter chạy script. Package
`faiss-cpu` cung cấp module import tên `faiss`. Kaggle restart session sẽ mất các
package đã cài; chạy lại hai lệnh trên trong mỗi session mới.

`transformers>=4.51.0` là bắt buộc vì model nền dùng kiến trúc Qwen3. PyTorch được
cài riêng theo GPU và không nằm trong `requirements.txt`.

Các cảnh báo dependency conflict liên quan `dask-cuda`, `cudf`, `cuml`,
`numba-cuda`, hoặc `cuda-core` là từ RAPIDS có sẵn trong image Kaggle; pipeline
này không import các package đó. Chúng không phải nguyên nhân của lỗi embedding
nếu lệnh pip kết thúc với exit code 0. Không cài hoặc nâng riêng `numba`,
`numba-cuda`, hay `cuda-core` cho pipeline này.

### 1.3. Gate bắt buộc trước khi chạy pipeline

```python
import torch
assert torch.cuda.is_available()
print("GPU count:", torch.cuda.device_count())
for i in range(torch.cuda.device_count()):
    capability = torch.cuda.get_device_capability(i)
    required_arch = f"sm_{capability[0]}{capability[1]}"
    assert required_arch in torch.cuda.get_arch_list(), (i, required_arch)
    print(i, torch.cuda.get_device_name(i), required_arch)
print(torch.__version__, torch.cuda.get_arch_list())
```

Pipeline kiểm tra compatibility trước khi tải model và sẽ fail-fast với hướng dẫn
cài đặt thay vì lỗi `no kernel image is available for execution on the device` ở
batch đầu tiên. Có thể dùng `--device cpu` để debug nhỏ, nhưng không phù hợp để
encode full corpus.

Khai báo path:

```python
CHUNKS = "/kaggle/input/<dataset>/chunks.parquet"
METADATA = "/kaggle/input/<dataset>/metadata.parquet"
WORK = "/kaggle/working/legal_embedding"
```

Nếu Kaggle tắt Internet, thêm model vào Kaggle Dataset và truyền đường dẫn local
qua `--model`.

## 2. Freeze embedding payload

```bash
!python prepare_embedding_data.py \
  --chunks "$CHUNKS" \
  --metadata "$METADATA" \
  --output-dir "$WORK/data" \
  --version v0.1 \
  --chunker-version v0.1
```

Output:

```text
legal_embedding/data/
  embed_payload_v0.1.parquet
  prepare_manifest.json
  table_repair_candidates.parquet
  prepare.log
```

`contextual_text` mặc định được rebuild bằng metadata và `section_path`. Dùng
`--keep-existing-context` chỉ khi file chunk đã có prefix metadata đầy đủ.

Pipeline sẽ dừng nếu gặp `raw_table` trong payload, `chunk_id` trùng, hoặc
`table_summary` vi phạm `answer_source=raw_table` /
`do_not_answer_from_summary=True`. `table_summary` thiếu raw table vẫn được
embed nhưng được ghi vào `table_repair_candidates.parquet`.

## 3. Debug encode trước

Luôn chạy một tập nhỏ trong **output directory riêng**:

```bash
!python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/debug_shards" \
  --batch-size 8 \
  --max-length 512 \
  --shard-size 1000 \
  --limit 100
```

Kiểm tra `manifest.json`, shape vector và log trước khi chạy full.

```bash
!test -f "$WORK/debug_shards/manifest.json" && echo "debug embedding OK"
```

Chỉ chạy encode full nếu command trên in `debug embedding OK`.

## 4. Encode full và resume

Pipeline mặc định gom các text có độ dài gần nhau vào cùng batch để giảm padding. Dùng
`batch-size` làm giới hạn số row và `token-budget` làm giới hạn padded-token per batch:
batch dài sẽ nhỏ, còn batch ngắn có thể chứa nhiều row hơn.

`token-budget = batch-size × max-length` là ngưỡng tối đa an toàn. Với T4/P100 16 GB và
model 1.2 GB float16, dùng `token-budget=49152` (48 × 1024) và `batch-size=128`.
Trên T4 16 GB, `131072` gây OOM (~128 rows × 1024 token cần thêm ~8 GB VRAM).
`encode_texts` tự chia batch khi OOM; vẫn nên giữ budget an toàn.

**Quan trọng khi chạy 2 GPU song song:** notebook/script launcher **không được**
`import torch` trước khi spawn worker. Parent giữ CUDA context trên GPU 0 sẽ chặn
worker `CUDA_VISIBLE_DEVICES=0`. Dùng `KAGGLE_MEMBER.py` (không import torch ở parent)
hoặc kiểm tra GPU bằng subprocess rồi mới spawn hai process.

```bash
!python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/data/shards" \
  --batch-size 128 \
  --token-budget 49152 \
  --max-length 1024 \
  --shard-size 10000 \
  --attn-implementation sdpa \
  --cache-dir /kaggle/working/.cache
```

Nếu CUDA OOM, giảm `--token-budget` theo bội số 2 (65536 → 32768). Không giảm
`max-length=1024` cho production chỉ để tăng tốc nếu chưa đánh giá retrieval quality.

Trước khi chạy full, benchmark đúng một shard production trong output directory riêng:

```bash
!python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/benchmark_shard" \
  --shard-start 0 --shard-stop 1 \
  --batch-size 384 --token-budget 131072 --max-length 1024 \
  --shard-size 10000 --attn-implementation sdpa
```

Mỗi shard log `rows/s`, `real tokens/s`, tỷ lệ padding và thời gian encode. Để hoàn tất
5 triệu rows trong 12 giờ, throughput trung bình phải đạt ít nhất `116 rows/s`; với
5,57 triệu rows phải đạt ít nhất `129 rows/s`. Sau shard đầu tiên, ước tính thời gian:

```text
ETA giờ = tổng số rows / rows_per_second / 3600
```

Nếu vẫn thấp hơn mục tiêu sau khi tăng `token-budget`, một T4/P100 không đủ để bảo đảm
deadline 12 giờ với model 600M và `max-length=1024`; cần chia payload và chạy song song
trên nhiều GPU hoặc dùng GPU nhanh hơn. Không chạy nhiều process trên cùng một GPU.

Ví dụ 5 triệu rows tương ứng 500 shard. Trong cùng runtime T4 x2, phải chạy hai process
đồng thời, gán rõ một GPU cho mỗi process và dùng output directory riêng. Nếu không gán
`CUDA_VISIBLE_DEVICES`, cả hai process mặc định sẽ tranh GPU 0:

```bash
# Chạy trong một cell Kaggle; dấu & làm hai process chạy đồng thời.
!CUDA_VISIBLE_DEVICES=0 python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/data/shards_0" \
  --shard-start 0 --shard-stop 250 \
  --batch-size 384 --token-budget 131072 --max-length 1024 \
  --shard-size 10000 --attn-implementation sdpa \
  > "$WORK/gpu0.log" 2>&1 & \
CUDA_VISIBLE_DEVICES=1 python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/data/shards_1" \
  --shard-start 250 --shard-stop 500 \
  --batch-size 384 --token-budget 131072 --max-length 1024 \
  --shard-size 10000 --attn-implementation sdpa \
  > "$WORK/gpu1.log" 2>&1 & \
wait
```

Mỗi process chỉ nhìn thấy một T4 và dùng device `cuda` của GPU đó. Kiểm tra lúc chạy:

```bash
!nvidia-smi
!tail -n 5 "$WORK/gpu0.log"
!tail -n 5 "$WORK/gpu1.log"
```

Không upload riêng từng thư mục `shards_0`/`shards_1` vào cùng Elasticsearch index:
uploader cần một manifest hoàn chỉnh để checkpoint an toàn. Hai thư mục từ ví
dụ thủ công này không trực tiếp Elasticsearch-ready khi đứng riêng. Với production phân tán,
dùng layout `KAGGLE_MEMBER.py` rồi tạo canonical shards bằng `repair_member_shards.py`;
`merge_member_shards.py` chỉ dùng cho member outputs strict, đầy đủ và không duplicate.
Nếu corpus không đúng tròn 5 triệu rows, tính số shard bằng
`ceil(total_rows / 10000)` rồi chia dải tương ứng.

Chạy lại đúng command để resume. Shard chỉ được đánh dấu `done` sau khi cả
`.npy` và `.parquet` đã ghi xong. Không đổi model, `max-length`, hoặc
`shard-size` trong cùng output directory.

```bash
!test -f "$WORK/data/shards/manifest.json" && echo "full embedding has manifest"
```

Elasticsearch upload chỉ được chạy sau khi manifest full embedding tồn tại. Lỗi
`Missing .../data/shards/manifest.json` nghĩa là bước encode full chưa chạy thành
công; không phải lỗi Elasticsearch.

Output mỗi shard:

```text
vectors_shard_00000.npy       # float16, normalized
payload_shard_00000.parquet
manifest.json
embed_run.log
```

Với khoảng 5.57 triệu chunk, riêng vector float16 đã gần 11.4 GB. Nên tạo
Kaggle Dataset từ thư mục shard trước khi build Qdrant.

Payload shard mặc định không lặp lại `chunk_text`/`contextual_text` để tiết
kiệm disk. Chỉ thêm `--include-text-in-payload` khi chắc chắn muốn lưu
`chunk_text` trực tiếp trong Qdrant.

## 5. Build compact FAISS indexes from Kaggle member datasets

When the five member datasets total about 30 GB, do not copy them into a merged
directory and do not build Qdrant beside them in `/kaggle/working`.
`KAGGLE_MERGE.py` now keeps member datasets read-only, ignores duplicate member
rows using first-occurrence-wins ordering, encodes only missing chunks, and
builds compact deduplicated per-member IVF-PQ indexes:

```bash
%run /kaggle/input/datasets/brdh7940/04-embedding/04_embedding/KAGGLE_MERGE.py
```

Publish `/kaggle/working/legal_embedding/faiss_members/`. Trong cùng session chạy
`KAGGLE_MERGE.py`, launcher đã cài và kiểm tra `faiss`. Trong session mới hoặc khi
chỉ add published FAISS dataset, phải cài dependency lại trước khi query:

```bash
cd /kaggle/input/datasets/brdh7940/04-embedding/04_embedding
python -m pip install -q -r requirements.txt
python -c "import faiss; print(faiss.__version__)"
python dense_retrieval.py \
  --faiss-dir /kaggle/working/legal_embedding/faiss_members \
  --chunks "$CHUNKS" \
  --query "Điều kiện cấp giấy phép xây dựng là gì?" \
  --top-k 5
```

The default `IVF4096,PQ64x8` stores about 64 bytes per vector plus IVF and
payload overhead. One shared codebook is trained and reused across all member
indexes so scores remain comparable when their local top-K results are merged.
FAISS metadata filters are post-filters; increase `--faiss-oversample` for
selective filters and measure recall with `evaluate_dense.py`.

## Elasticsearch on Elastic Cloud

Install the official Python client through the project requirements:

```powershell
python -m pip install -r requirements.txt
```

The API key previously pasted into a terminal or chat must be revoked in Elastic
Cloud and replaced. Keep the replacement credentials out of source files, logs,
and manifests. Environment variables avoid putting the key in process arguments,
but a literal assignment can still remain in PowerShell history. Prefer a secret
manager or a non-persisted shell session:

```powershell
$env:ELASTIC_CLOUD_ID="your-deployment-cloud-id"
$env:ELASTIC_API_KEY="your-new-api-key"
```

### Trial-safe upload

Benchmark one source shard before uploading the whole corpus:

```powershell
python pipeline/04_embedding/build_elasticsearch.py `
  --shards-dir "data/embedding/shards" `
  --index "legal_chunks_dense_v1" `
  --recreate `
  --max-shards 1 `
  --workers 2 `
  --upsert-batch 500 `
  --max-chunk-mb 20 `
  --queue-size 2
```

If the benchmark is stable, resume the remaining source shards by removing
`--recreate` and `--max-shards`:

```powershell
python pipeline/04_embedding/build_elasticsearch.py `
  --shards-dir "data/embedding/shards" `
  --index "legal_chunks_dense_v1" `
  --workers 2 `
  --upsert-batch 500 `
  --max-chunk-mb 20 `
  --queue-size 2
```

Source shard files are processed sequentially so a completed shard can be resumed
deterministically. Within each source shard, `--workers` sends multiple bulk HTTP
requests concurrently. Do not run multiple uploader processes against the same
manifest.

For a trial deployment, start with 2 workers and 500 documents per request. Watch
`elasticsearch_build.log` and Elastic Cloud monitoring for HTTP 429 responses,
CPU saturation, JVM memory pressure, and falling rows per second. Change only one
setting per benchmark. If the cluster remains stable, try 3 workers or a batch of
750. If 429 responses or long retries appear, reduce workers first, then reduce
the batch size. More client threads can make a small trial deployment slower.

Capacity remains a separate constraint from upload speed. About 5.7 million
1024-dimensional float32 vectors require roughly 23.3 GB for raw vector values
before metadata and ANN index overhead. A small trial deployment may not fit the
full corpus. After the one-shard benchmark, compare projected index size, JVM
memory pressure, and remaining disk capacity before starting the complete upload.

During ingest the script sets `refresh_interval=-1` and zero replicas. It restores
the configured final settings only after all selected source shards are complete.
Use `--recreate` only when intentionally deleting and rebuilding the target index.

The resumable checkpoint is written to
`data/embedding/shards/elasticsearch_manifest.json`. Credentials are never written
to this file.

### Elasticsearch retrieval

```powershell
python pipeline/04_embedding/dense_retrieval.py `
  --elastic-cloud-id $env:ELASTIC_CLOUD_ID `
  --elastic-index "legal_chunks_dense_v1" `
  --chunks "data/legal_chunking_dataset/chunks.parquet" `
  --query "Dieu kien cap giay phep xay dung la gi?" `
  --top-k 5 `
  --elastic-num-candidates 100
```

`ELASTIC_API_KEY` is read from the environment. Exact, list, and range filters use
Elasticsearch kNN pre-filtering. Returned scores are converted from Elasticsearch's
positive `_score` representation back to raw cosine similarity so they remain
comparable with the existing dense retrieval contract.

### Elasticsearch evaluation

```powershell
python pipeline/07_evaluation/evaluate_dense.py `
  --gold "output/eval_questions_gold.jsonl" `
  --elastic-cloud-id $env:ELASTIC_CLOUD_ID `
  --elastic-index "legal_chunks_dense_v1" `
  --elastic-num-candidates 2000 `
  --chunks "data/legal_chunking_dataset/chunks.parquet" `
  --candidate-k 100 `
  --top-k 10 `
  --output "output/elasticsearch_dense_eval.json"
```

Increase `--elastic-num-candidates` only when evaluation shows a useful recall gain;
larger values increase query CPU and latency.

## 7. Smoke test retrieval

```bash
python dense_retrieval.py \
  --elastic-cloud-id "$ELASTIC_CLOUD_ID" \
  --chunks /data/chunks.parquet \
  --query "Điều kiện cấp giấy phép xây dựng là gì?" \
  --filters '{"effect_status":"Còn hiệu lực","ranges":{"issuance_date_ts":{"gte":20200101}}}'
```

Output mỗi hit có contract:

```json
{
  "chunk_id": "...",
  "dense_score": 0.81,
  "payload": {},
  "citation": "...",
  "optional_expanded_context": "..."
}
```

`table_summary` được expand sang `raw_table`; `procedure_record` và
`clause_group` được expand theo rule trong code khi có `chunks.parquet`.

## 8. Dense evaluation

Tạo file UTF-8 JSONL, mỗi dòng:

```json
{"query":"...","group":"article","relevant_chunk_ids":["..."],"relevant_doc_ids":[123],"filters":null}
{"query":"...","group":"metadata_filter","relevant_doc_ids":[456],"filters":{"effect_status":"Còn hiệu lực"}}
```

Chạy:

```bash
!python pipeline/07_evaluation/evaluate_dense.py \
  --gold /kaggle/input/<eval-dataset>/dense_gold.jsonl \
  --elastic-cloud-id "$ELASTIC_CLOUD_ID" \
  --chunks "$CHUNKS" \
  --top-k 10 \
  --output "$WORK/logs/dense_eval.json"
```

Báo cáo gồm Recall@10, MRR@10, nDCG@10 tổng và theo `group`.

## Dense retrieval + reranking

Reranking retrieves and deduplicates a larger dense candidate pool before scoring
metadata-aware `(query, passage_text)` pairs. If model initialization or scoring
fails, evaluation logs the exception and falls back to dense order.

```bash
python pipeline/07_evaluation/evaluate_dense.py \
  --gold pipeline/07_evaluation/eval_questions_gold.jsonl \
  --url http://129.212.184.109:8333/ \
  --chunks data/legal_chunking_dataset/chunks.parquet \
  --candidate-k 100 \
  --top-k 10 \
  --rerank \
  --reranker-model BAAI/bge-reranker-v2-m3 \
  --output data/legal_embedding/dense_rerank_eval_results.json
```

GPU is selected automatically when available, or explicitly with `--device`.
Use `--rerank-batch-size` to control reranker memory usage. The output contains
both dense baseline and reranked metrics, candidate dense scores, rerank scores,
and final ordered results.

## Lưu ý vận hành

- Document được encode **không có query prefix**. Prefix chỉ dùng trong
  `dense_retrieval.py` khi encode query.
- Vector shard lưu float16; lúc upsert được chuyển thành float32.
- Không xóa shard sau khi upload Elasticsearch. Đây là artifact portable để rebuild.
- Nếu đổi model, revision, max length hoặc chunk version, dùng output directory
  và collection version mới.
- Full shard files và Elasticsearch store có thể vượt giới hạn disk Kaggle.
  Khi đó chỉ encode/export shard trên Kaggle và upload Elasticsearch ở môi trường khác.
