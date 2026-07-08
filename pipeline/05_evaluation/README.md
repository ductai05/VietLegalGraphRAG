# 📈 Bước 7: Đánh giá mô hình (Evaluation)

Đánh giá hiệu suất hệ thống GraphRAG trên các benchmark và test cases.

## Tạo bộ câu hỏi đánh giá (Evaluation Questions)

Script `generate_eval_questions.py` tạo ~200 câu hỏi trắc nghiệm (multiple-choice) từ các chunks văn bản pháp luật bằng Gemini API (`gemma-4-31b-it`).

### Yêu cầu

```bash
# Cài đặt dependencies
pip install google-genai python-dotenv
```

Tạo file `.env` ở thư mục gốc project với nội dung:
```
GEMINI_API_KEY=your_api_key_here
```

### Sử dụng

```bash
# Dry-run: chỉ sampling, không gọi API (kiểm tra dữ liệu)
python pipeline/05_evaluation/generate_eval_questions.py --dry-run

# Chạy đầy đủ: sampling + generate questions
python pipeline/05_evaluation/generate_eval_questions.py

# Chạy với seed tùy chỉnh
python pipeline/05_evaluation/generate_eval_questions.py --seed 123

# Resume từ checkpoint (nếu bị gián đoạn)
python pipeline/05_evaluation/generate_eval_questions.py --resume
```

### Output

File `eval_questions.json` chứa:
- **metadata**: thông tin về quá trình tạo (model, seed, timestamp)
- **questions**: array gồm ~200 câu hỏi, mỗi câu gồm:
  - `question_id`: ID duy nhất
  - `question`: Câu hỏi trắc nghiệm (tiếng Việt)
  - `choices`: 4 lựa chọn A/B/C/D
  - `answer`: Đáp án đúng
  - `difficulty`: Mức độ khó (easy/medium/hard)
  - `evidence`: Bằng chứng gồm chunk_ids, chunk_texts, doc_id, doc_title, legal_type, section_path
  - `question_type`: Loại câu hỏi (factual/inference/procedural/comparison)
  - `reasoning`: Giải thích đáp án

### Chiến lược Sampling

1. **Stratified random sampling** ~60 documents theo `legal_type` (Luật, Nghị định, Thông tư...)
2. Chỉ lấy documents `Còn hiệu lực`
3. Mỗi document chọn 3-5 chunks liên tiếp (sử dụng linked-list `prev_chunk_id`/`next_chunk_id`)
4. Chỉ lấy chunk types có ý nghĩa: article, clause_group, preamble, procedure_record, v.v.

## LLM response evaluation

`evaluate_llm.py` compares closed-book multiple-choice answering against the
best retrieval setup (hybrid dense + BM25 RRF + reranking). It hydrates the
saved top-10 chunk IDs from Elasticsearch, calls the configured Groq models,
and writes resumable JSONL results plus aggregate metrics.

Required variables in `.env`:

```dotenv
ELASTIC_CLOUD_ID=...
ELASTIC_API_KEY=...
GROQ_API_KEY=...
GROQ_API_KEY2=...
GROQ_API_KEY3=...
```

All variables whose names start with `GROQ_API_KEY` form a reloadable key pool.
Duplicate key values are ignored. Parallel model processes should use different
`--groq-key-offset` values. On HTTP 429 the evaluator reloads `.env`, rotates
to an available key, and therefore picks up keys added while it is running.
Groq limits may still be shared when multiple keys belong to the same
organization.

Smoke test:

```bash
python pipeline/05_evaluation/evaluate_llm.py --limit 2
```

Full benchmark:

```bash
python pipeline/05_evaluation/evaluate_llm.py
```

Outputs are written under `output/llm_evaluation/`:

- `contexts.jsonl`: hydrated top-10 context used by the RAG setup
- `responses.jsonl`: one checkpointed record per question/model/setup
- `summary.json`: accuracy, citation, retrieval-hit, latency, and token metrics

The default context budget is 4,000 characters to remain reproducible under
Groq's 6,000 TPM free-tier limit. All ten ranked chunks remain represented;
the text budget is weighted toward the highest ranks (25%, 15%, 10%, then an
equal share for ranks 4-10), keeping both the start and end of truncated chunks.

## Hybrid Elasticsearch search

`hybrid_search.py` is the smoke test and evaluation entrypoint for the merged
Elasticsearch hybrid index. Use the same alias for dense and sparse search:
`vietlegal_chunks`.

Recommended smoke query:

```text
thủ tục cấp giấy phép xây dựng
```

RRF strategy:

- Dense phase runs kNN over `embedding`.
- Sparse phase runs BM25 over the Vietnamese tokenized text fields.
- The script fuses both ranked lists with 1-based Reciprocal Rank Fusion:
  `score = sum(1 / (rrf_k + rank))`.
- Use `--rrf-k 60` as the default. Lower values make top ranks more dominant;
  higher values soften the difference between ranks.
- Reranking should happen after RRF, not before. The reranker receives the top
  `--candidate-k` fused candidates and reorders them with
  `BAAI/bge-reranker-v2-m3`.

Smoke test without reranker:

```powershell
python pipeline/05_evaluation/hybrid_search.py `
  --env-file src/infra/production.env `
  --index vietlegal_chunks `
  --query "thủ tục cấp giấy phép xây dựng" `
  --candidate-k 50 `
  --top-k 10 `
  --rrf-k 60 `
  --elastic-num-candidates 1000
```

Smoke test with BGE reranker:

```powershell
python pipeline/05_evaluation/hybrid_search.py `
  --env-file src/infra/production.env `
  --index vietlegal_chunks `
  --query "thủ tục cấp giấy phép xây dựng" `
  --candidate-k 50 `
  --top-k 10 `
  --rrf-k 60 `
  --elastic-num-candidates 1000 `
  --rerank `
  --reranker-model BAAI/bge-reranker-v2-m3 `
  --rerank-batch-size 8 `
  --device cuda
```

Use `--device cpu` if CUDA is not available. On CPU, reduce
`--candidate-k` to 20 or 30 for quick checks.

Full hybrid evaluation with reranker:

```powershell
python pipeline/05_evaluation/hybrid_search.py `
  --env-file src/infra/production.env `
  --index vietlegal_chunks `
  --gold output/eval_questions_gold.jsonl `
  --candidate-k 100 `
  --top-k 10 `
  --k-values 1 3 5 10 `
  --rrf-k 60 `
  --elastic-num-candidates 1000 `
  --rerank `
  --reranker-model BAAI/bge-reranker-v2-m3 `
  --rerank-batch-size 8 `
  --device cuda `
  --output output/elasticsearch_hybrid_bge_rerank_eval.json
```

If the gold file is still in `eval_questions.json` format, pass that file with
`--chunks <path-to-chunks.parquet>` so the script can convert it to JSONL first.
