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
