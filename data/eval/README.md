# Evaluation Data

Thư mục này chứa các artifact phục vụ đánh giá hệ thống, ví dụ tập câu hỏi, gold labels, kết quả chạy retrieval và kết quả chấm LLM.

## Nội dung thường gặp

- `questions.json`: câu hỏi đánh giá dạng JSON.
- `questions_gold.jsonl`: nhãn gold theo `chunk_id`, `doc_id` hoặc metadata liên quan.
- Kết quả evaluation sinh ra từ pipeline.

## Lưu ý

Dữ liệu trong thư mục này có thể lớn hoặc thay đổi theo từng lần chạy. Repository chỉ track README và placeholder, không track dataset hay output đánh giá thật.
