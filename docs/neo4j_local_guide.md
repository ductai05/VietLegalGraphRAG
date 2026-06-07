# Hướng dẫn Thiết lập Cơ sở dữ liệu Đồ thị Tri thức Neo4j (Local Setup Guide)

Tài liệu này hướng dẫn cách chạy và nạp dữ liệu Đồ thị Tri thức Pháp luật Việt Nam vào cơ sở dữ liệu Neo4j cục bộ trên máy cá nhân bằng Docker.

---

## 1. Yêu cầu chuẩn bị (Prerequisites)

1. **Docker Desktop**: Tải và cài đặt [Docker Desktop](https://www.docker.com/products/docker-desktop/) trên Windows. Đảm bảo Docker Desktop đã được bật (biểu tượng cá voi màu xanh lá ở góc dưới màn hình).
2. **File dữ liệu**: Tải file `neo4j_imports.zip` từ thư mục Drive nhóm về máy.

---

## 2. Các bước triển khai (Setup Steps)

### Bước 1: Chuẩn bị thư mục dữ liệu
1. Trong thư mục đồ án trên máy của bạn, tạo đường dẫn thư mục: `data/processed/neo4j_imports` nếu chưa có.
2. Giải nén toàn bộ nội dung của tệp `neo4j_imports.zip` vào thư mục này. 
   *(Lưu ý: Sau khi giải nén, bên trong thư mục `neo4j_imports` phải chứa trực tiếp 12 tệp CSV, ví dụ: `articles.csv`, `documents.csv`, `doc_doc_edges.csv`,...)*

### Bước 2: Chạy kịch bản nạp dữ liệu tự động (Bulk Import)
Mở PowerShell tại thư mục gốc của dự án (`VietLegalGraphRAG`) và chạy lệnh sau:

```powershell
powershell -File pipeline/04_graph_construction/import_and_verify.ps1
```

---

## 3. Thời gian chạy & Kết nối

*   **Thời gian chạy**: Khoảng **15 phút** (bao gồm 13.5 phút chạy nạp dữ liệu và 1.5 phút để khởi động máy chủ + chạy kiểm thử API).
*   **Thông tin kết nối sau khi hoàn tất**:
    *   🔗 **Web Browser (Giao diện đồ họa)**: [http://localhost:7474](http://localhost:7474)
    *   ⚡ **Connection Bolt URI (Python API)**: `bolt://localhost:7687`
    *   🔑 **Username**: `neo4j`
    *   🔒 **Password**: `password123`

---

## 4. Các câu lệnh Cypher cơ bản để kiểm tra nhanh

Truy cập [http://localhost:7474](http://localhost:7474), đăng nhập bằng tài khoản trên, và nhập các câu lệnh Cypher sau vào thanh lệnh ở đầu trang để kiểm tra:

### 4.1. Đếm số lượng văn bản của từng cơ quan ban hành (Authority)
```cypher
MATCH (d:Document)-[:ISSUED_BY]->(a:Authority)
RETURN a.name AS AuthorityName, count(d) AS DocumentCount
ORDER BY DocumentCount DESC
LIMIT 10
```

### 4.2. Xem liên kết giữa văn bản và 5 đoạn nội dung (Chunk) đầu tiên
```cypher
MATCH (d:Document)-[:HAS_CHUNK]->(c:Article)
RETURN d.document_number, c.id, c.token_estimate
LIMIT 5
```
