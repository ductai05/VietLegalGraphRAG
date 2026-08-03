# Pipeline 06 — LightRAG Integration for VietLegalGraphRAG

Thư mục này chứa toàn bộ pipeline thử nghiệm tích hợp thư viện **[hkuds/LightRAG](https://github.com/HKUDS/LightRAG)** vào hệ thống VietLegalGraphRAG.

> **Mục tiêu**: Đánh giá khả năng LightRAG thay thế hoặc bổ sung cho pipeline Elasticsearch + Neo4j hiện tại, với entity/relation graph được xây dựng từ văn bản pháp luật Việt Nam thông qua LLM inference trên GPU Droplet (H100 + vLLM).

## Tài liệu

| File | Mô tả |
|------|-------|
| [`spec.md`](spec.md) | Đặc tả kỹ thuật đầy đủ (architecture, data flow, component design) |
| [`plan.md`](plan.md) | Kế hoạch triển khai theo phase |
| [`task.md`](task.md) | Danh sách task chi tiết có thể tracking |
| [`decision_log.md`](decision_log.md) | Log các quyết định thiết kế và lý do |

## Cấu trúc thư mục (dự kiến)

```text
pipeline/06_lightrag/
  config/
    lightrag_config.example.env     # Template cấu hình
  src/
    ingest.py                       # Ingestion: đọc corpus → LightRAG indexing
    query.py                        # Query: truy vấn LightRAG index
    extract_entities.py             # (Optional) Pre-extract entities cho legal domain
    legal_ontology.py               # Legal ontology / type hints cho entity extraction
    evaluate_lightrag.py            # So sánh LightRAG vs pipeline hiện tại
    utils.py                        # Shared utilities
  notebooks/
    01_explore_lightrag.ipynb       # Khám phá LightRAG API
    02_index_corpus.ipynb           # Thử nghiệm indexing
    03_query_evaluation.ipynb       # Đánh giá query quality
  requirements.txt
  README.md                         # File này
```

## Nhanh bắt đầu

```bash
# 1. Cài đặt dependencies
pip install -r pipeline/06_lightrag/requirements.txt

# 2. Copy và cấu hình
cp pipeline/06_lightrag/config/lightrag_config.example.env .env.lightrag
# Điền VLLM_BASE_URL, VLLM_MODEL, OPENAI_API_KEY (cho query LLM), v.v.

# 3. Chạy ingestion (build LightRAG index)
python pipeline/06_lightrag/src/ingest.py --config .env.lightrag --input data/preprocessed/

# 4. Thử query
python pipeline/06_lightrag/src/query.py --config .env.lightrag --query "Điều kiện thành lập công ty TNHH?"
```

## Liên quan

- Pipeline hiện tại: [`pipeline/04_graph/`](../04_graph/) — Neo4j graph construction
- Evaluation framework: [`pipeline/05_evaluation/`](../05_evaluation/) — Metric scripts
- Runtime service: [`src/vietlegal_rag/services/lightrag_service.py`](../../src/vietlegal_rag/services/lightrag_service.py)
- LegalGraphRAG (ACL'26) reference: https://github.com/XMUDeepLIT/LegalGraphRAG
