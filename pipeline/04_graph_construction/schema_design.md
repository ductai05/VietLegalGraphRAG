# Thiết kế Đồ thị Tri thức (KG Schema Design)

Tài liệu này định nghĩa chi tiết về cấu trúc các nút (Nodes), các mối quan hệ (Edges) và các thuộc tính tương ứng để xây dựng Đồ thị Tri thức phục vụ cho GraphRAG pháp luật Việt Nam, khớp nối 100% với tài liệu Notion của nhóm.

---

## 1. Các Node (Nhãn thực thể) và Khóa chính (PK)

### 1.1. Node: `Document` (Văn bản pháp luật)
Đại diện cho văn bản pháp lý cấp cao nhất.
- **Khóa chính**: `doc:<id>` (ví dụ: `doc:10000000012`).
- **Thuộc tính**:
  - `id:ID(Document)`: Định danh chuẩn hóa dạng `doc:<id>`.
  - `title`: Tiêu đề đầy đủ của văn bản.
  - `document_number`: Số ký hiệu văn bản (ví dụ: `15/2020/NĐ-CP`).
  - `legal_type`: Loại văn bản (ví dụ: `Luật`, `Nghị định`).
  - `legal_sectors`: Danh sách lĩnh vực thô (chuỗi phân tách bằng dấu phẩy).
  - `issuing_authority`: Cơ quan ban hành.
  - `issuance_date`: Ngày ban hành (YYYY-MM-DD).
  - `effect_date`: Ngày có hiệu lực (YYYY-MM-DD).
  - `effectless_date`: Ngày hết hiệu lực (YYYY-MM-DD).
  - `effect_status`: Tình trạng hiệu lực (ví dụ: `Còn hiệu lực`, `Hết hiệu lực`).
  - `signers`: Người ký.
  - `source`: Nguồn dữ liệu (`data`, `legacy`, hoặc `legacy+data`).
  - `priority_tier` (Derived): Phân tầng ưu tiên pháp lý (Tier 1, Tier 2, Tier 3, Unknown).
  - `sector_list` (Derived): Mảng các lĩnh vực pháp luật đã được cắt nhỏ.

### 1.2. Node: `Chunk` (Đoạn nội dung)
Đại diện cho nội dung chi tiết trong văn bản, được chia nhỏ từ quá trình chunking.
- **Khóa chính**: `chunk:<doc_id>:<ordinal>` (với `ordinal` định dạng 6 chữ số kèm số 0 đi trước, ví dụ: `chunk:12345:000000`).
- **Thuộc tính**:
  - `id:ID(Article)`: Định danh chuẩn hóa dạng `chunk:<doc_id>:<ordinal>`.
  - `chunk_id`: UUID gốc từ pipeline chunking để duy trì tham chiếu ngược.
  - `doc_id`: ID văn bản gốc chứa chunk này.
  - `chunk_type`: Loại chunk (ví dụ: `article`, `preamble`, `table_part`).
  - `section_path`: Phân cấp thư mục dạng JSON.
  - `procedure_name`: Tên thủ tục hành chính nếu thuộc bảng thủ tục.
  - `embed`: Giá trị boolean cho biết có embed chunk này hay không.
  - `keyword_index`: Giá trị boolean cho biết có lập chỉ mục từ khóa hay không.
  - `token_estimate`: Số lượng token ước tính của chunk.
  - `quality_flags`: Danh sách cảnh báo chất lượng dưới dạng mảng JSON.
  - `unresolved_parent_ref`: Chứa mã hash `parent_id` gốc nếu không thể resolve được thành Node Chunk cha trong đồ thị.

### 1.3. Node: `LegalType` (Loại văn bản)
- **Khóa chính**: `legal_type:<normalized_value>` (ví dụ: `legal_type:luat`, `legal_type:nghi_dinh`).

### 1.4. Node: `Authority` (Cơ quan ban hành)
- **Khóa chính**: `authority:<normalized_value>` (ví dụ: `authority:quoc_hoi`, `authority:chinh_phu`).
- **Thuộc tính**:
  - `name`: Tên đầy đủ hiển thị của cơ quan.

### 1.5. Node: `Sector` (Lĩnh vực pháp luật)
- **Khóa chính**: `sector:<normalized_value>` (ví dụ: `sector:doanh_nghiep`, `sector:thue`).
- **Thuộc tính**:
  - `name`: Tên đầy đủ hiển thị của lĩnh vực.

---

## 2. Các Edge (Mối quan hệ)

### 2.1. Quan hệ Siêu dữ liệu (Metadata Edges)
Nối Document với các Node thông tin chuẩn hóa:
- `Document -[:HAS_LEGAL_TYPE]-> LegalType`
- `Document -[:ISSUED_BY]-> Authority`
- `Document -[:IN_SECTOR]-> Sector`

### 2.2. Quan hệ Cấu trúc Chunk (Chunk Edges)
Mô tả cấu trúc nội dung bên trong một văn bản:
- `Document -[:HAS_CHUNK]-> Chunk`
- `Chunk -[:NEXT_CHUNK]-> Chunk` (Nối các chunk kề nhau tuần tự theo văn bản).
- `Chunk -[:PARENT_OF]-> Chunk` (Nối từ chunk cha đến chunk con, chỉ tạo khi `parent_id` giải nghĩa được).

### 2.3. Quan hệ giữa Document - Document (Được làm sạch & Chuẩn hóa)
Gộp các quan hệ thô từ file `relationships.parquet` sang 4 nhãn chính:
- **`AMENDS`**: Văn bản nguồn sửa đổi/bổ sung văn bản đích.
- **`CITES`**: Văn bản nguồn trích dẫn/dẫn chiếu hoặc liên quan văn bản đích.
- **`REPEALS`**: Văn bản nguồn bãi bỏ hoặc làm hết hiệu lực văn bản đích.
- **`GUIDELINES`**: Văn bản nguồn hướng dẫn chi tiết văn bản đích.

*Quy ước hướng cạnh*: Luôn đi từ văn bản thực thi/sửa đổi/trích dẫn (mới hơn) sang văn bản bị sửa đổi/được trích dẫn (cũ hơn). Đối với các mối quan hệ bị động thô (dạng `IS_..._BY`), code tự động đảo ngược hướng để nhất quán chiều đi.
Ví dụ: `A IS_AMENDED_BY B` sẽ được lưu thành `B -[:AMENDS]-> A`.

---

## 3. Thuật toán phân cấp Chunk (`PARENT_OF`)
Mỗi chunk khi xuất ra được tính một khóa băm duy nhất cho đường dẫn mục lục của nó:
`section_hash = stable_hash(doc_id + "::" + " > ".join(section_path))`
Mỗi chunk con mang theo trường `parent_id` đại diện cho băm của cha nó.
- Nếu tồn tại một chunk khác trong cùng tài liệu có `section_hash == parent_id`, ta tạo cạnh `ParentChunk -[:PARENT_OF]-> ChildChunk`.
- Nếu không tìm thấy, ta lưu giá trị băm đó vào trường `unresolved_parent_ref` của Node Chunk con.
