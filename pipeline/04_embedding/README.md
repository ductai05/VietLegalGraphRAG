# Dense Embedding Pipeline

Pipeline này hiện thực kế hoạch trong `PLAN_EMBEDDING.md` cho model
`darklethelong/vnlegal-lal`:

1. Lọc `embed=True`, loại `raw_table` và `hard_char_split`.
2. Join metadata, rebuild `contextual_text`, chuẩn hóa ngày.
3. Encode theo shard float16, có manifest để resume.
4. Upsert shard vào Qdrant local hoặc Qdrant server.
5. Dense retrieval, expansion và đánh giá Recall/MRR/nDCG.

## Các file

| File | Vai trò |
|---|---|
| `prepare_embedding_data.py` | Freeze `embed_payload_v0.1.parquet`, kiểm tra invariant và xuất danh sách bảng cần repair |
| `embed_shards.py` | Encode document theo shard, checkpoint bằng `manifest.json` |
| `build_qdrant.py` | Tạo collection/index và resume upsert shard |
| `dense_retrieval.py` | Query prefix, filter, citation và expansion từ `chunks.parquet` |
| `evaluate_dense.py` | Tính Recall@K, MRR@K, nDCG@K từ gold JSONL |
| `embedding_common.py` | Hằng số và utility dùng chung |

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
!pip install -q -r requirements.txt
```

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
`batch-size` lớn làm giới hạn số row và `token-budget` làm giới hạn bộ nhớ cho batch:
batch dài sẽ nhỏ, còn batch ngắn có thể chứa nhiều row hơn. Với T4/P100 16 GB, bắt đầu
với ngân sách tương đương batch 16 ở độ dài 1024:

```bash
!python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/data/shards" \
  --batch-size 128 \
  --token-budget 16384 \
  --max-length 1024 \
  --shard-size 10000 \
  --attn-implementation sdpa \
  --cache-dir /kaggle/working/.cache
```

Nếu CUDA OOM, giảm `--token-budget` xuống `12288` hoặc `8192`. Nếu GPU còn nhiều VRAM,
tăng lên `24576` rồi `32768`. Không giảm `max-length=1024` cho production chỉ để tăng
tốc nếu chưa đánh giá retrieval quality.

Trước khi chạy full, benchmark đúng một shard production trong output directory riêng:

```bash
!python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/benchmark_shard" \
  --shard-start 0 --shard-stop 1 \
  --batch-size 128 --token-budget 16384 --max-length 1024 \
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
  --batch-size 128 --token-budget 16384 --max-length 1024 \
  --shard-size 10000 --attn-implementation sdpa \
  > "$WORK/gpu0.log" 2>&1 & \
CUDA_VISIBLE_DEVICES=1 python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/data/shards_1" \
  --shard-start 250 --shard-stop 500 \
  --batch-size 128 --token-budget 16384 --max-length 1024 \
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

Sau đó upsert lần lượt hai thư mục vào cùng Qdrant collection; chỉ job đầu tiên dùng
`--recreate`. Nếu corpus không đúng tròn 5 triệu rows, tính số shard bằng
`ceil(total_rows / 10000)` rồi chia dải tương ứng.

Chạy lại đúng command để resume. Shard chỉ được đánh dấu `done` sau khi cả
`.npy` và `.parquet` đã ghi xong. Không đổi model, `max-length`, hoặc
`shard-size` trong cùng output directory.

```bash
!test -f "$WORK/data/shards/manifest.json" && echo "full embedding has manifest"
```

`build_qdrant.py` chỉ được chạy sau khi manifest full embedding tồn tại. Lỗi
`Missing .../data/shards/manifest.json` nghĩa là bước encode full chưa chạy thành
công; không phải lỗi Qdrant.

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

## 5. Build Qdrant

### Qdrant embedded local

Chỉ chạy trên Kaggle nếu còn đủ disk:

```bash
!python build_qdrant.py \
  --shards-dir "$WORK/data/shards" \
  --storage-dir "$WORK/qdrant/qdrant_storage" \
  --recreate \
  --archive "$WORK/qdrant/qdrant_legal_chunks_dense_v1.zip"
```

Sau lần đầu, bỏ `--recreate` để resume. Không dùng `--include-text` mặc định
vì `chunk_text` làm payload và Qdrant storage tăng mạnh; retrieval có thể lấy
text/expansion từ `chunks.parquet`.

Qdrant embedded local phù hợp smoke test, nhưng payload index không có hiệu lực
như Qdrant server. Với full corpus, nên ingest shard trên máy có đủ disk vào
Qdrant server:

```bash
python build_qdrant.py \
  --shards-dir /data/legal_embedding/shards \
  --url http://localhost:6333 \
  --recreate
```

Nếu server yêu cầu key, thêm `--api-key "$QDRANT_API_KEY"`.

## 6. Smoke test retrieval

Local:

```bash
!python dense_retrieval.py \
  --storage-dir "$WORK/qdrant/qdrant_storage" \
  --chunks "$CHUNKS" \
  --query "Điều kiện cấp giấy phép xây dựng là gì?" \
  --top-k 5
```

Qdrant server:

```bash
python dense_retrieval.py \
  --url http://localhost:6333 \
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

## 7. Dense evaluation

Tạo file UTF-8 JSONL, mỗi dòng:

```json
{"query":"...","group":"article","relevant_chunk_ids":["..."],"relevant_doc_ids":[123],"filters":null}
{"query":"...","group":"metadata_filter","relevant_doc_ids":[456],"filters":{"effect_status":"Còn hiệu lực"}}
```

Chạy:

```bash
!python evaluate_dense.py \
  --gold /kaggle/input/<eval-dataset>/dense_gold.jsonl \
  --storage-dir "$WORK/qdrant/qdrant_storage" \
  --chunks "$CHUNKS" \
  --top-k 10 \
  --output "$WORK/logs/dense_eval.json"
```

Báo cáo gồm Recall@10, MRR@10, nDCG@10 tổng và theo `group`.

## Lưu ý vận hành

- Document được encode **không có query prefix**. Prefix chỉ dùng trong
  `dense_retrieval.py` khi encode query.
- Vector shard lưu float16; lúc upsert được chuyển thành float32.
- Không xóa shard sau khi build Qdrant. Đây là artifact portable để rebuild.
- Nếu đổi model, revision, max length hoặc chunk version, dùng output directory
  và collection version mới.
- Qdrant local và file shard cùng tồn tại có thể vượt giới hạn disk Kaggle.
  Khi đó chỉ encode/export shard trên Kaggle và build Qdrant ở môi trường khác.
