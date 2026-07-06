# Data Directory

Thư mục `data/` chứa các artifact dữ liệu của VietLegalGraphRAG. Dữ liệu thật, index, vector, file parquet, csv lớn và các checkpoint sinh ra từ pipeline không được commit lên Git. Repository chỉ track `README.md` và `.gitkeep` để remote vẫn hiển thị được cấu trúc thư mục.

## Nguyên tắc track file

- Commit: `README.md`, `.gitkeep`.
- Không commit: parquet, csv, json/jsonl dataset, vector `.npy`, index, checkpoint, snapshot, log.
- Mỗi artifact nên được tạo lại bằng pipeline từ `data/raw/` hoặc tải về từ storage ngoài repo.

## Cấu trúc

```text
data/
├── raw/
│   └── vietnamese_legal_documents/
├── processed/
│   ├── cleaned/
│   └── chunks/
├── retrieval/
│   ├── dense/
│   │   └── vnlegal_lal_v0.1/
│   │       ├── payload/
│   │       └── vectors/
│   ├── sparse/
│   │   └── bm25_v0.1/
│   └── graph/
│       └── kg_v0.1/
│           ├── edges/
│           └── nodes/
└── eval/
```

## Vai trò từng nhóm

- `raw/`: dữ liệu gốc tải từ nguồn bên ngoài, chưa qua xử lý.
- `processed/`: dữ liệu đã làm sạch, chuẩn hóa và chunking, làm đầu vào cho retrieval và graph.
- `retrieval/`: artifact phục vụ truy xuất, gồm dense vectors, sparse/BM25 payload và knowledge graph export.
- `eval/`: tập câu hỏi, gold labels và artifact cần cho đánh giá retrieval/LLM.
