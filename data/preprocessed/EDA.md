# CLEANED EDA: Tập dữ liệu pháp luật Việt Nam (sau tiền xử lý)

> Báo cáo này mô tả trạng thái dữ liệu **sau khi tiền xử lý**:
>
> - Loại bỏ trùng lặp nội dung (theo `id`)
> - Chỉ giữ lại văn bản **còn hiệu lực** (`effect_status = "Còn hiệu lực"`)
> - Xoá cột `thong_tin_ap_dung` (100% null)
> - Đồng bộ `content`, `metadata`, `relationships` theo tập `id` còn lại

---

## 1. Tổng quan

| Thuộc tính                     | Giá trị                                                              |
| ------------------------------ | -------------------------------------------------------------------- |
| **Miền**                       | Pháp luật Việt Nam                                                   |
| **Mục đích**                   | Hybrid RAG (dense vector + keyword + LightRAG) cho hỏi đáp pháp luật |
| **Số văn bản (còn hiệu lực)**  | **348,623**                                                          |
| **Số metadata records**        | 348,623                                                              |
| **Số quan hệ (relationships)** | **61,700** (sau lọc theo active docs)                                |
| **Khoảng thời gian**           | 1924-08-25 → 2026-03-25                                              |
| **Định dạng lưu trữ**          | Parquet (3 files)                                                    |

---

## 2. Cấu trúc file (sau lọc)

| File                          | Số dòng | Cột | Dung lượng (ước) |
| ----------------------------- | ------- | --- | ---------------- |
| `content_clean.parquet`       | 348,623 | 3   | ~6.1 MB          |
| `metadata_clean.parquet`      | 348,623 | 18  | ~160 MB          |
| `relationships_clean.parquet` | 61,700  | 3   | ~2.3 MB          |

> **Ghi chú**: Dung lượng giảm mạnh do chỉ giữ lại văn bản còn hiệu lực.

---

## 3. Schema các bảng

### 3.1 `content`

| Cột       | Kiểu   | Null | Mô tả                                  |
| --------- | ------ | ---- | -------------------------------------- |
| `id`      | Int64  | 0    | Khóa chính, liên kết với metadata      |
| `content` | String | 0    | Toàn văn văn bản pháp luật             |
| `source`  | String | 0    | Nguồn: `legacy`, `legacy+data`, `data` |

### 3.2 `metadata`

Đã loại bỏ cột `thong_tin_ap_dung` (100% null).

| Cột                  | Null % | Mô tả                                                 |
| -------------------- | ------ | ----------------------------------------------------- |
| `id`                 | 0%     | Khóa chính                                            |
| `document_number`    | 0%     | Số hiệu văn bản                                       |
| `title`              | 0%     | Tiêu đề                                               |
| `legal_type`         | ~0%    | Loại văn bản (Quyết định, Công văn, ...)              |
| `legal_sectors`      | 2.39%  | Lĩnh vực pháp lý (đa giá trị, cách `, `)              |
| `issuing_authority`  | 0.06%  | Cơ quan ban hành                                      |
| `issuance_date`      | 0%     | Ngày ban hành (`YYYY-MM-DD`)                          |
| `effect_date`        | 0.24%  | Ngày có hiệu lực                                      |
| `effectless_date`    | 97.81% | Ngày hết hiệu lực (hầu hết null vì đang còn hiệu lực) |
| `effect_status`      | 0%     | Chỉ có `Còn hiệu lực`                                 |
| `signers`            | 0.1%   | Người ký                                              |
| `nguon_thu_thap`     | 90.82% | Nguồn thu thập                                        |
| `ngay_dang_cong_bao` | 95.61% | Ngày đăng công báo                                    |
| `nganh`              | 90.12% | Ngành                                                 |
| `linh_vuc`           | 95.41% | Lĩnh vực                                              |
| `chuc_danh`          | 83.18% | Chức danh người ký                                    |
| `pham_vi`            | 84.59% | Phạm vi áp dụng                                       |
| `source`             | 0%     | Nguồn gốc dữ liệu                                     |

### 3.3 `relationships`

| Cột            | Kiểu   | Null | Mô tả                |
| -------------- | ------ | ---- | -------------------- |
| `doc_id`       | Int64  | 0    | Văn bản gốc          |
| `other_doc_id` | Int64  | 0    | Văn bản liên quan    |
| `relationship` | String | 0    | Loại quan hệ pháp lý |

---

## 4. Chất lượng dữ liệu

### 4.1 Trùng lặp

- **Không còn duplicate** `id` trong `content` (đã xử lý `unique(subset=['id'])`)
- **Không còn `content` trùng lặp chính xác** giữa các `id` khác nhau

### 4.2 Null fields đáng chú ý

- Các cột `effectless_date`, `ngay_dang_cong_bao`, `linh_vuc`, `nganh`, `nguon_thu_thap` có tỷ lệ null > 90% → **không nên dùng làm bộ lọc chính**.
- `legal_sectors` chỉ null 2.39% → **rất tốt cho filtering/tagging**.
- Các cột core (`id`, `title`, `document_number`, `legal_type`, `issuance_date`) **không null**.

### 4.3 Đồng bộ ID

- `content.id` và `metadata.id` hoàn toàn trùng khớp (348,623 IDs)
- Toàn bộ các `doc_id` và `other_doc_id` trong `relationships` đều tồn tại trong metadata (29,276 unique nodes)

---

## 5. Phân tích nội dung

### 5.1 Phân phối độ dài văn bản (số ký tự)

| Thống kê     | Giá trị   |
| ------------ | --------- |
| Trung bình   | 12,824    |
| Trung vị     | 4,687     |
| tứ phân vị 1 | 2,194     |
| tứ phân vị 3 | 12,899    |
| Nhỏ nhất     | 9         |
| Lớn nhất     | 4,585,077 |

**Phân bố theo nhóm độ dài:**

| Nhóm         | Số văn bản  | %         |
| ------------ | ----------- | --------- |
| < 500 ký tự  | 527         | 0.15%     |
| 500 – 2K     | 74,734      | 21.4%     |
| 2K – 5K      | 105,316     | 30.2%     |
| **5K – 20K** | **111,466** | **32.0%** |
| 20K – 100K   | 51,809      | 14.9%     |
| > 100K       | 4,771       | 1.37%     |

> ⚠️ **Hệ quả cho RAG**: Hơn 60% văn bản có độ dài từ 2K–20K ký tự. Chiến lược chunking phù hợp:
>
> - `chunk_size ≈ 512–1024 tokens`, `overlap ≈ 128 tokens` cho phần lớn văn bản.
> - Với văn bản > 100K (~4.8k văn bản) cần chunking phân cấp (hierarchical chunking).

### 5.2 Phân bố nguồn (`source`)

**Trong `content`:**

| Nguồn         | Số lượng | %     |
| ------------- | -------- | ----- |
| `legacy`      | 295,791  | 84.8% |
| `legacy+data` | 33,108   | 9.5%  |
| `data`        | 19,724   | 5.7%  |

**Trong `metadata`** (tương tự, có sai lệch nhỏ do đồng bộ):

| Nguồn         | Số lượng | %     |
| ------------- | -------- | ----- |
| `legacy`      | 288,745  | 82.8% |
| `legacy+data` | 40,154   | 11.5% |
| `data`        | 19,724   | 5.7%  |

---

## 6. Phân tích metadata

### 6.1 Loại văn bản (`legal_type`)

| Loại văn bản       | Số lượng | %     |
| ------------------ | -------- | ----- |
| **Quyết định**     | 166,759  | 47.8% |
| **Công văn**       | 122,284  | 35.1% |
| Nghị quyết         | 27,732   | 8.0%  |
| Chỉ thị            | 10,879   | 3.1%  |
| Thông tư           | 8,338    | 2.4%  |
| Nghị định          | 2,531    | 0.7%  |
| Thông báo          | 1,729    | 0.5%  |
| Hướng dẫn          | 1,600    | 0.5%  |
| Thông tư liên tịch | 1,570    | 0.5%  |
| Điều ước quốc tế   | 1,239    | 0.4%  |
| Còn lại (10 loại)  | ~4,000   | 1.1%  |

### 6.2 Hiệu lực (`effect_status`)

**Chỉ có một giá trị:** `Còn hiệu lực` (348,623 văn bản)

> ✅ **RAG implication**: Toàn bộ corpus đều đang có hiệu lực, không cần filter thêm. Có thể an toàn trả lời các câu hỏi về quy định hiện hành.

### 6.3 Phân bố theo năm (top 20)

| Năm  | Số văn bản |
| ---- | ---------- |
| 2026 | 2,987      |
| 2025 | 30,462     |
| 2024 | 25,035     |
| 2023 | 21,806     |
| 2022 | 18,253     |
| 2021 | 19,097     |
| 2020 | 17,580     |
| 2019 | 15,304     |
| 2018 | 15,077     |
| 2017 | 17,157     |
| 2016 | 17,279     |
| 2015 | 14,109     |
| 2014 | 16,346     |
| 2013 | 15,986     |
| 2012 | 12,513     |
| 2011 | 10,386     |
| 2010 | 10,244     |
| 2009 | 9,488      |
| 2008 | 10,148     |
| 2007 | 8,374      |

> **Nhận xét**: Lượng văn bản còn hiệu lực cao nhất rơi vào các năm 2021–2026, phản ánh sự cập nhật liên tục. Các văn bản từ năm 2000 trở về trước vẫn còn hiệu lực nhưng với số lượng ít hơn.

### 6.4 Cơ quan ban hành hàng đầu (`issuing_authority`)

| Cơ quan                 | Số văn bản |
| ----------------------- | ---------- |
| Tổng cục Thuế           | 22,634     |
| Tổng cục Hải quan       | 19,983     |
| Thủ tướng Chính phủ     | 15,108     |
| Văn phòng Chính phủ     | 12,301     |
| Bộ Tài chính            | 11,620     |
| Bộ Xây dựng             | 8,334      |
| Bộ Nông nghiệp và PTNT  | 6,444      |
| Thành phố Hà Nội        | 5,567      |
| Cục thuế TP Hà Nội      | 5,367      |
| Cục Thuế TP Hồ Chí Minh | 5,160      |
| Bộ Y tế                 | 4,960      |
| Chính phủ               | 4,493      |

### 6.5 Lĩnh vực pháp lý (`legal_sectors`)

- **Tỷ lệ non-null**: 97.6% (340,274/348,623)
- **Số lượng tag unique** (sau khi tách chuỗi): **1,508**
- **Top tag xuất hiện nhiều nhất**:

| Tag                | Số lần xuất hiện |
| ------------------ | ---------------- |
| Bộ máy hành chính  | 92,401           |
| phí                | 51,225           |
| lệ phí             | 50,572           |
| Thuế               | 50,572           |
| Xuất nhập khẩu     | 29,752           |
| Tài chính nhà nước | 27,444           |
| Văn hóa - xã hội   | 26,943           |
| Xây dựng - đô thị  | 23,972           |
| Thương mại         | 20,394           |
| Thể thao - y tế    | 20,330           |

> **Lưu ý**: Tag `phí`, `lệ phí`, `Thuế` xuất phát từ việc tách chuỗi `"Thuế - lệ phí"`. Có thể gộp lại thành `Thuế - lệ phí` để tránh trùng lặp.

---

## 7. Đồ thị quan hệ (Relationships)

### 7.1 Thống kê tổng quan

| Thông số                    | Giá trị |
| --------------------------- | ------- |
| Tổng số cạnh                | 61,700  |
| Số node duy nhất (`doc_id`) | 29,276  |
| Số node trong graph         | 29,276  |
| Tất cả node đều có metadata | ✅ Có   |
| Out-degree trung bình       | 2.36    |
| Out-degree trung vị         | 2       |
| Out-degree lớn nhất         | 71      |

### 7.2 Phân bố loại quan hệ

| Loại quan hệ                                 | Số cạnh | %     |
| -------------------------------------------- | ------- | ----- |
| **Văn bản căn cứ**                           | 47,676  | 77.3% |
| Văn bản dẫn chiếu                            | 7,473   | 12.1% |
| Văn bản được HD, QĐ chi tiết                 | 2,424   | 3.9%  |
| Văn bản HD, QĐ chi tiết                      | 2,422   | 3.9%  |
| Văn bản bổ sung / được bổ sung               | 1,181   | 1.9%  |
| Văn bản hết hiệu lực / quy định hết hiệu lực | 396     | 0.6%  |
| Các loại khác                                | ~128    | 0.2%  |

> **LightRAG implication**: Quan hệ `Văn bản căn cứ` chiếm ưu thế tuyệt đối → có thể xây dựng **dependency graph** mạnh mẽ. Các quan hệ sửa đổi/hết hiệu lực tuy ít nhưng rất quan trọng cho version tracking.

### 7.3 Các văn bản có nhiều quan hệ nhất

| `doc_id` | Số quan hệ |
| -------- | ---------- |
| 38522    | 71         |
| 268473   | 59         |
| 96988    | 52         |
| 13988    | 40         |
| 45434    | 36         |
| 141479   | 36         |

---

## 8. Khuyến nghị cho Hybrid RAG Pipeline

### 8.1 Tiền xử lý (đã hoàn thành)

```python
# Đã thực hiện:
content = content.unique(subset=["id"])
metadata = metadata.drop("thong_tin_ap_dung")
metadata = metadata.filter(pl.col("effect_status") == "Còn hiệu lực")
# Đồng bộ relationships
```

```

### 8.2 Chiến lược chunking

| Độ dài văn bản | Chiến lược                                         |
| -------------- | -------------------------------------------------- |
| < 2K ký tự     | Không chunk, dùng nguyên document                  |
| 2K – 20K       | Chunk 512–1024 tokens, overlap 128 tokens          |
| 20K – 100K     | Recursive chunking theo điều/khoản                 |
| > 100K         | Hierarchical chunking (section → article → clause) |

### 8.3 Các trường metadata hữu ích cho filtering/retrieval

- `legal_type` – lọc theo loại văn bản
- `issuing_authority` – lọc theo cơ quan ban hành
- `issuance_date` – lọc theo khoảng thời gian
- `legal_sectors` (cần split `", "`) – lọc theo lĩnh vực

### 8.4 Tích hợp LightRAG với đồ thị quan hệ

- Dùng `relationships_clean.parquet` làm edge list
- Node attributes lấy từ `metadata_clean` (title, legal_type, issuance_date)
- Loại `Văn bản căn cứ` là primary edge cho graph traversal
- Các loại `Văn bản hết hiệu lực`, `Văn bản sửa đổi` (dù số lượng ít) nên được bảo toàn để hỗ trợ truy vấn lịch sử phiên bản.

---

**Báo cáo được sinh từ:**
`content_clean.parquet`, `metadata_clean.parquet`, `relationships_clean.parquet`
**Ngày tạo:** 2026-05-31
```
