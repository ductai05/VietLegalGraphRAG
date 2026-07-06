# Processed Data

Thư mục này chứa dữ liệu đã qua tiền xử lý, làm sạch, chuẩn hóa và chunking, sẵn sàng làm đầu vào cho retrieval, graph và evaluation.

## Cấu trúc

```text
processed/
├── cleaned/
│   ├── content.parquet
│   ├── metadata.parquet
│   └── relationships.parquet
└── chunks/
    ├── chunks_v0.1.parquet
    └── metadata_v0.1.parquet
```

## Vai trò

- `cleaned/`: dữ liệu văn bản và metadata sau bước làm sạch.
- `chunks/`: retrieval units đã chunk, có `chunk_id`, `doc_id`, `chunk_type`, text/context và các flag index.

## Lưu ý

Thư mục này bị Git ignore đối với data artifact. Chỉ `README.md` và `.gitkeep` được track để giữ cấu trúc trên remote. Không chỉnh sửa trực tiếp các file parquet, hãy tạo lại bằng pipeline khi cần.
