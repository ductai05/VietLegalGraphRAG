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

Đưa thư mục `04_embedding` lên Kaggle Dataset hoặc clone repo, sau đó:

```bash
%cd /kaggle/working/VietLegalGraphRAG/pipeline/04_embedding
!pip install -q -r requirements.txt
```

`transformers>=4.51.0` là bắt buộc vì model nền dùng kiến trúc Qwen3.
PyTorch được cài riêng theo GPU, không nằm trong `requirements.txt`, vì wheel PyTorch
mới có thể không còn kernel cho Tesla P100 (`sm_60`).

Kiểm tra GPU và các CUDA architecture có trong wheel hiện tại:

```python
import torch
print(torch.__version__, torch.cuda.get_device_name(0), torch.cuda.get_arch_list())
```

Nếu GPU là **Tesla P100** và danh sách không có `sm_60`, chạy cell sau **trước khi
import pipeline**, rồi restart Kaggle session:

```bash
!pip install --force-reinstall --no-cache-dir torch==2.7.1 \
  --index-url https://download.pytorch.org/whl/cu118
```

Sau khi restart, chạy lại cell kiểm tra và xác nhận `sm_60` xuất hiện. Không dùng
`pip install -U torch` trên P100. Với T4 (`sm_75`), giữ wheel Kaggle mặc định nếu
`torch.cuda.get_arch_list()` có `sm_75`.

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

## 4. Encode full và resume

T4 nên bắt đầu với `batch-size=16`; giảm batch size nếu CUDA OOM. Không giảm
`max-length=1024` cho production chỉ để tăng tốc.

```bash
!python embed_shards.py \
  --payload "$WORK/data/embed_payload_v0.1.parquet" \
  --output-dir "$WORK/data/shards" \
  --batch-size 16 \
  --max-length 1024 \
  --shard-size 10000 \
  --cache-dir /kaggle/working/.cache
```

Chạy lại đúng command để resume. Shard chỉ được đánh dấu `done` sau khi cả
`.npy` và `.parquet` đã ghi xong. Không đổi model, `max-length`, hoặc
`shard-size` trong cùng output directory.

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
