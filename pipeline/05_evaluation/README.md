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
python pipeline/07_evaluation/generate_eval_questions.py --dry-run

# Chạy đầy đủ: sampling + generate questions
python pipeline/07_evaluation/generate_eval_questions.py

# Chạy với seed tùy chỉnh
python pipeline/07_evaluation/generate_eval_questions.py --seed 123

# Resume từ checkpoint (nếu bị gián đoạn)
python pipeline/07_evaluation/generate_eval_questions.py --resume
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
python pipeline/07_evaluation/evaluate_llm.py --limit 2
```

Full benchmark:

```bash
python pipeline/07_evaluation/evaluate_llm.py
```

Outputs are written under `output/llm_evaluation/`:

- `contexts.jsonl`: hydrated top-10 context used by the RAG setup
- `responses.jsonl`: one checkpointed record per question/model/setup
- `summary.json`: accuracy, citation, retrieval-hit, latency, and token metrics

The default context budget is 4,000 characters to remain reproducible under
Groq's 6,000 TPM free-tier limit. All ten ranked chunks remain represented;
the text budget is weighted toward the highest ranks (25%, 15%, 10%, then an
equal share for ranks 4-10), keeping both the start and end of truncated chunks.
