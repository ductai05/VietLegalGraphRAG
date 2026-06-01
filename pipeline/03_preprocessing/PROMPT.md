# Context

Context: Tôi đang xây dựng chatbot cho luật pháp Việt Nam:

```
import polars as pl

content = pl.read_parquet(CONTENT_PATH)
metadata = pl.read_parquet(META_PATH)
relationships = pl.read_parquet(REL_PATH)
```

Trong đó:

- `content` có schema `Schema([('id', Int64), ('content', String), ('source', String)])`.
- `metadata` chứa metadata của `content` thì có schema như sau:

```
Schema([('id', Int64),
        ('document_number', String),
        ('title', String),
        ('legal_type', String),
        ('legal_sectors', String),
        ('issuing_authority', String),
        ('issuance_date', String),
        ('effect_date', String),
        ('effectless_date', String),
        ('effect_status', String),
        ('signers', String),
        ('nguon_thu_thap', String),
        ('ngay_dang_cong_bao', String),
        ('nganh', String),
        ('linh_vuc', String),
        ('chuc_danh', String),
        ('pham_vi', String),
        ('source', String)])
```

- `relationships` chứa quan hệ của các document trong `content` với schema: `Schema([('doc_id', Int64), ('other_doc_id', Int64), ('relationship', String)])`

Tiếp theo, tôi sẽ cần phải đào sâu vào `content['content']` vì đây là nơi chứa các đoạn text của văn bản luật Việt Nam. Vì tôi build chatbot nên tôi phải tìm kiếm chiến lược chunking phù hợp, vì mục tiêu của tôi là build hệ thống hybrid RAG (Dense vector search + keyword matching + lightRAG).
