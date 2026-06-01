# Context

Context: Tôi đang xây dựng chatbot cho luật pháp Việt Nam:

```
import polars as pl

content = pl.read_parquet(CONTENT_PATH)
```

Trong đó, `content` có schema `Schema([('id', Int64), ('content', String), ('source', String)])`. Tiếp theo, tôi sẽ cần phải đào sâu vào `content['content']` vì đây là nơi chứa các đoạn text của văn bản luật Việt Nam. Vì tôi build chatbot nên tôi phải tìm kiếm chiến lược chunking phù hợp, vì mục tiêu của tôi là build hệ thống hybrid RAG (Dense vector search + keyword matching + lightRAG).
