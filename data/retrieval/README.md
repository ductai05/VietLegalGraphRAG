# Retrieval Artifacts

Thư mục này chứa artifact được tạo sau các bước indexing và graph construction để phục vụ truy xuất trong RAG.

## Cấu trúc

```text
retrieval/
├── dense/
│   └── vnlegal_lal_v0.1/
│       ├── manifest.json
│       ├── payload/
│       └── vectors/
├── sparse/
│   └── bm25_v0.1/
└── graph/
    └── kg_v0.1/
        ├── edges/
        └── nodes/
```

## Vai trò

- `dense/`: payload shard và vector shard cho dense retriever.
- `sparse/`: payload/index cho sparse retriever, ví dụ BM25.
- `graph/`: nodes và edges export từ knowledge graph, dùng cho expansion, citation và phân tích liên kết pháp lý.

Artifact trong thư mục này là output sinh ra từ pipeline. Không commit vector, index, parquet, csv lớn, snapshot Qdrant/Elasticsearch hoặc checkpoint.
