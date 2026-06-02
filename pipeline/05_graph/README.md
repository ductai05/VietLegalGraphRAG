# Bước 4: Xây dựng Knowledge Graph

Module này xây dựng Knowledge Graph từ dữ liệu đã làm sạch trong `data/preprocessed/`.

Đầu vào chính:

- `metadata.parquet`: node văn bản và metadata catalog.
- `relationships.parquet`: quan hệ pháp lý giữa văn bản.
- `legal_chunks.parquet` hoặc chunk output tương đương: tùy chọn, dùng để gắn chunk vào document graph.

Đầu ra mặc định nằm trong `data/graph/`, thư mục này đang được `.gitignore` bỏ qua.

## Thiết kế

Chi tiết thiết kế nằm ở:

- `docs/superpowers/specs/2026-06-02-knowledge-graph-design.md`
- `docs/superpowers/plans/2026-06-02-knowledge-graph.md`

Pipeline chọn hướng artifact-first:

1. Sinh node và edge table cục bộ.
2. Xuất CSV, JSON summary và Cypher import.
3. Import Neo4j là bước tùy chọn sau khi kiểm tra artifact.

Cách này phù hợp với repo hiện tại vì chưa có cấu hình Neo4j trong `.env`.

## Cài đặt

```powershell
pip install -r pipeline/05_graph/requirements.txt
```

Miniconda hiện tại trên máy đã có `pandas`, `pyarrow`, `networkx`; nếu dùng môi trường khác thì cài theo file requirements.

## Chạy sample

Chạy smoke build trên một phần metadata:

```powershell
python pipeline/05_graph/run_graph_construction.py `
  --metadata data/preprocessed/metadata.parquet `
  --relationships data/preprocessed/relationships.parquet `
  --output-dir data/graph_sample `
  --limit 1000
```

Chạy full document graph:

```powershell
python pipeline/05_graph/run_graph_construction.py `
  --metadata data/preprocessed/metadata.parquet `
  --relationships data/preprocessed/relationships.parquet `
  --output-dir data/graph
```

Khi đã có chunk output:

```powershell
python pipeline/05_graph/run_graph_construction.py `
  --metadata data/preprocessed/metadata.parquet `
  --relationships data/preprocessed/relationships.parquet `
  --chunks data/preprocessed/legal_chunks.parquet `
  --output-dir data/graph
```

## Artifact

Các file bắt buộc:

- `nodes.csv`: tất cả node, gồm `Document`, `LegalType`, `Authority`, `Sector`, và `Chunk` nếu có chunks.
- `edges.csv`: tất cả edge đã chuẩn hóa.
- `documents.csv`: document node table để inspect.
- `document_relationship_edges.csv`: cạnh pháp lý giữa văn bản.
- `graph_summary.json`: số lượng node, edge, orphan, duplicate, phân bố relation.
- `neo4j_import.cypher`: script import CSV vào Neo4j.

Các file tùy chọn khi có chunks:

- `chunks.csv`
- `chunk_edges.csv`

## Node và edge chính

Node:

- `Document`
- `Chunk`
- `LegalType`
- `Authority`
- `Sector`

Edge metadata:

- `HAS_LEGAL_TYPE`
- `ISSUED_BY`
- `IN_SECTOR`

Edge pháp lý:

- `CITES_AS_BASIS`
- `CITES`
- `GUIDES_DETAIL`
- `IS_GUIDED_DETAILED_BY`
- `AMENDS`
- `IS_AMENDED_BY`
- `SUPPLEMENTS`
- `IS_SUPPLEMENTED_BY`
- `REPLACES_OR_EXPIRES`
- `IS_REPLACED_OR_EXPIRED_BY`
- `SUSPENDS`
- `IS_SUSPENDED_BY`
- `RELATED_TO`

Edge chunk:

- `HAS_CHUNK`
- `NEXT_CHUNK`
- `PARENT_OF` chỉ được sinh khi resolve được hai endpoint chunk.

## Neo4j import

Copy CSV và `neo4j_import.cypher` vào thư mục import của Neo4j, sau đó chạy Cypher bằng Neo4j Browser hoặc `cypher-shell`.

Script hiện dùng `apoc.create.relationship` để tạo relationship type động từ `edges.csv`, vì vậy Neo4j cần cài APOC. Nếu không dùng APOC, tách `edges.csv` theo từng `type` và viết `LOAD CSV` riêng cho từng loại edge.

## Lưu ý về chunk ID

`pipeline/03_preprocessing/chunk.py` đã dùng ID ổn định theo mẫu:

```text
chunk:<doc_id>:<ordinal>
```

Ví dụ: `chunk:42:000001`. Điều này cần thiết để vector index, BM25 index và KG không bị lệch sau mỗi lần chạy lại chunking.

## Kiểm thử

```powershell
python -m pytest tests -q
```

