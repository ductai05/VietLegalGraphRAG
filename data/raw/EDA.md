## 1. Overview

| Property                      | Value                                                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------ |
| **Domain**                    | Pháp luật Việt Nam (Vietnamese Law)                                                                    |
| **Purpose**                   | Xây dựng hệ thống Hybrid RAG (dense vector search + keyword matching + LightRAG) cho hỏi đáp pháp luật |
| **Total documents (content)** | 593,409 rows / 564,136 unique IDs                                                                      |
| **Total metadata records**    | 564,136                                                                                                |
| **Total relationships**       | 775,522 edges                                                                                          |
| **Date range**                | 1924-08-25 → 2026-03-30                                                                                |
| **Storage format**            | Parquet (3 files)                                                                                      |

---

## 2. File Structure

| File                           | Rows    | Columns | Size (est.) |
| ------------------------------ | ------- | ------- | ----------- |
| `merged_content.parquet`       | 593,409 | 3       | ~10,342 MB  |
| `merged_metadata.parquet`      | 564,136 | 19      | ~258 MB     |
| `merged_relationships.parquet` | 775,522 | 3       | ~29 MB      |

---

## 3. Table Schemas

### 3.1 `merged_content`

| Column    | Type   | Null | Description                                    |
| --------- | ------ | ---- | ---------------------------------------------- |
| `id`      | Int64  | 0    | Document ID (FK → metadata.id)                 |
| `content` | String | 0    | Full text của văn bản pháp luật                |
| `source`  | String | 0    | Nguồn dữ liệu: `legacy`, `legacy+data`, `data` |

### 3.2 `merged_metadata`

| Column               | Type   | Null % | Description                                    |
| -------------------- | ------ | ------ | ---------------------------------------------- |
| `id`                 | Int64  | 0%     | Primary key                                    |
| `document_number`    | String | 0%     | Số hiệu văn bản (vd: `34/2025/QĐ-UBND`)        |
| `title`              | String | 0%     | Tiêu đề văn bản                                |
| `legal_type`         | String | ~0%    | Loại văn bản (Quyết định, Công văn, ...)       |
| `legal_sectors`      | String | 3.08%  | Lĩnh vực pháp lý (multi-value, phân cách `, `) |
| `issuing_authority`  | String | 0.04%  | Cơ quan ban hành                               |
| `issuance_date`      | String | ~0%    | Ngày ban hành (format: `YYYY-MM-DD`)           |
| `effect_date`        | String | 0.35%  | Ngày có hiệu lực                               |
| `effectless_date`    | String | 75.95% | Ngày hết hiệu lực                              |
| `effect_status`      | String | 8.24%  | Trạng thái hiệu lực                            |
| `signers`            | String | 0.12%  | Người ký                                       |
| `nguon_thu_thap`     | String | 85.72% | Nguồn thu thập                                 |
| `ngay_dang_cong_bao` | String | 92.81% | Ngày đăng công báo                             |
| `nganh`              | String | 84.16% | Ngành                                          |
| `linh_vuc`           | String | 92.26% | Lĩnh vực                                       |
| `chuc_danh`          | String | 75.31% | Chức danh người ký                             |
| `pham_vi`            | String | 77.16% | Phạm vi áp dụng                                |
| `thong_tin_ap_dung`  | String | 100%   | ⚠️ Toàn bộ null — bỏ qua                       |
| `source`             | String | 0%     | Nguồn: `legacy`, `legacy+data`, `data`         |

### 3.3 `merged_relationships`

| Column         | Type   | Null | Description          |
| -------------- | ------ | ---- | -------------------- |
| `doc_id`       | Int64  | 0    | Document gốc         |
| `other_doc_id` | Int64  | 0    | Document liên quan   |
| `relationship` | String | 0    | Loại quan hệ pháp lý |

---

## 4. Data Quality Notes

### 4.1 Duplicate rows trong `content`

- **29,273 IDs** xuất hiện 2 lần → tổng **29,273 rows dư**
- Tất cả duplicates là **exact content match** (cùng `id`, cùng `source`, cùng `content`)
- ✅ **Xử lý**: `content.unique(subset=["id"])` là an toàn

### 4.2 Null fields đáng chú ý

- `thong_tin_ap_dung`: **100% null** → loại bỏ hoàn toàn khỏi pipeline
- `ngay_dang_cong_bao`, `linh_vuc`, `nguon_thu_thap`, `nganh`: null >84% → chỉ dùng khi available
- `effectless_date`, `chuc_danh`, `pham_vi`: null ~75% → optional enrichment fields
- Các fields core (`id`, `title`, `document_number`, `legal_type`, `issuance_date`): null < 0.01%

### 4.3 ID alignment

- `content.id` và `metadata.id` **khớp hoàn toàn** (sau khi deduplicate content): 564,136 IDs
- `relationships` graph bao gồm **124,638 unique nodes**, tất cả đều có trong metadata

---

## 5. Content Analysis

### 5.1 Document length distribution (ký tự)

| Bucket       | Count       | %                         |
| ------------ | ----------- | ------------------------- |
| < 500 chars  | 1,129       | 0.19%                     |
| 500 – 2K     | 100,982     | 17.02%                    |
| 2K – 5K      | 165,872     | 27.95%                    |
| **5K – 20K** | **213,835** | **36.04%** ← modal bucket |
| 20K – 100K   | 103,094     | 17.37%                    |
| > 100K       | 8,497       | 1.43%                     |

| Statistic    | Value                     |
| ------------ | ------------------------- |
| Mean         | 14,055 chars              |
| Median (p50) | 5,957 chars               |
| p75          | 15,443 chars              |
| Max          | 4,585,077 chars (~4.4 MB) |

> ⚠️ **RAG implication**: Phần lớn documents (36%) nằm trong 5K–20K chars. Cần chunking strategy với `chunk_size ≈ 512–1024 tokens`, `overlap ≈ 128 tokens`. Documents >100K (~8.5K docs) cần xử lý đặc biệt (hierarchical chunking).

### 5.2 Source distribution

| Source        | Content rows    | Metadata rows   |
| ------------- | --------------- | --------------- |
| `legacy`      | 437,153 (73.7%) | 422,464 (74.9%) |
| `legacy+data` | 102,476 (17.3%) | 95,661 (17.0%)  |
| `data`        | 53,780 (9.1%)   | 46,011 (8.2%)   |

---

## 6. Metadata Analysis

### 6.1 Document types (`legal_type`)

| Loại văn bản       | Count   | %     |
| ------------------ | ------- | ----- |
| Quyết định         | 276,851 | 49.1% |
| Công văn           | 124,451 | 22.1% |
| Nghị quyết         | 51,934  | 9.2%  |
| Kế hoạch           | 32,731  | 5.8%  |
| Thông tư           | 19,682  | 3.5%  |
| Chỉ thị            | 18,982  | 3.4%  |
| Thông báo          | 15,277  | 2.7%  |
| Nghị định          | 6,745   | 1.2%  |
| Thông tư liên tịch | 3,709   | 0.7%  |
| Luật               | 771     | 0.1%  |
| _(others)_         | 7,001   | 1.2%  |

### 6.2 Effect status (`effect_status`)

| Status                | Count   | %     |
| --------------------- | ------- | ----- |
| Còn hiệu lực          | 348,623 | 61.8% |
| Hết hiệu lực          | 163,440 | 29.0% |
| null                  | 46,507  | 8.2%  |
| Hết hiệu lực một phần | 5,121   | 0.9%  |
| Ngưng hiệu lực        | 371     | 0.1%  |
| Chưa có hiệu lực      | 72      | ~0%   |

> ⚠️ **RAG implication**: Nên **filter `effect_status = 'Còn hiệu lực'`** làm primary corpus (~348K docs). Có thể giữ lại "Hết hiệu lực" cho historical queries nhưng cần tag rõ ràng.

### 6.3 Temporal distribution (top years)

| Năm       | Số văn bản |
| --------- | ---------- |
| 2025      | 37,390     |
| 2024      | 36,099     |
| 2023      | 32,984     |
| 2022      | 29,789     |
| 2021      | 30,890     |
| 2020      | 27,690     |
| 2017–2019 | ~78,000    |
| 2010–2016 | ~161,000   |
| < 2010    | ~83,000    |
| 1924–1999 | (lịch sử)  |

### 6.4 Top issuing authorities

| Cơ quan             | Count  |
| ------------------- | ------ |
| Tổng cục Hải quan   | 27,341 |
| Tổng cục Thuế       | 22,873 |
| Thủ tướng Chính phủ | 18,816 |
| Bộ Tài chính        | 16,491 |
| Văn phòng Chính phủ | 16,190 |
| Thành phố Hà Nội    | 9,795  |
| Bộ Xây dựng         | 9,289  |
| Bộ NN&PTNT          | 8,623  |
| Chính phủ           | 7,554  |
| Bộ Y tế             | 7,387  |

### 6.5 Top legal sectors (`legal_sectors`)

> Field dạng multi-value (phân cách `, `). Tổng **2,370 unique sector tags**.

| Sector                  | Occurrences |
| ----------------------- | ----------- |
| Bộ máy hành chính       | 147,179     |
| Thuế - lệ phí           | ~60,244     |
| Văn hóa - xã hội        | 47,564      |
| Tài chính nhà nước      | 46,604      |
| Xuất nhập khẩu          | 39,049      |
| Xây dựng - đô thị       | 32,428      |
| Thương mại              | 31,938      |
| Tài nguyên - môi trường | 31,925      |
| Thể thao - y tế         | 30,571      |
| Bất động sản            | 29,596      |

---

## 7. Relationships Graph

| Metric                         | Value               |
| ------------------------------ | ------------------- |
| Total edges                    | 775,522             |
| Unique source nodes (`doc_id`) | 122,724             |
| Unique nodes (src + dst)       | 124,638             |
| All nodes covered by metadata  | ✅ Yes              |
| Mean out-degree                | 6.32                |
| Median out-degree              | 5                   |
| Max out-degree                 | 602 (doc_id: 48836) |

### Relationship types

| Loại quan hệ                   | Count   | %     |
| ------------------------------ | ------- | ----- |
| Văn bản căn cứ                 | 509,245 | 65.7% |
| Văn bản dẫn chiếu              | 66,567  | 8.6%  |
| Văn bản hết hiệu lực           | 45,394  | 5.9%  |
| Văn bản quy định hết hiệu lực  | 44,154  | 5.7%  |
| Văn bản được HD/QĐ chi tiết    | 33,670  | 4.3%  |
| Văn bản HD/QĐ chi tiết         | 33,436  | 4.3%  |
| Văn bản bổ sung                | 11,705  | 1.5%  |
| Văn bản sửa đổi / được sửa đổi | ~13,030 | 1.7%  |
| _(others)_                     | ~18,321 | 2.4%  |

> **LightRAG implication**: Graph này là **pre-built knowledge graph** cho LightRAG. `Văn bản căn cứ` (65.7%) thể hiện dependency chain pháp lý — rất có giá trị cho graph traversal khi truy vấn.

---

## 8. Recommendations cho Hybrid RAG Pipeline

### 8.1 Data preprocessing

```python
# Bước 1: Deduplicate content
content_clean = content.unique(subset=["id"])  # 593,409 → 564,136 rows

# Bước 2: Join content + metadata
full_df = content_clean.join(metadata, on="id", how="inner")

# Bước 3: Drop cột 100% null
full_df = full_df.drop("thong_tin_ap_dung")

# Bước 4 (optional): Filter chỉ lấy văn bản còn hiệu lực
active_df = full_df.filter(pl.col("effect_status") == "Còn hiệu lực")
# → ~348,623 documents
```

### 8.2 Chunking strategy

| Document size    | Strategy                                           |
| ---------------- | -------------------------------------------------- |
| < 2K chars       | Không chunk, dùng nguyên document                  |
| 2K – 20K chars   | Chunk 512–1024 tokens, overlap 128 tokens          |
| 20K – 100K chars | Recursive chunking theo điều/khoản                 |
| > 100K chars     | Hierarchical chunking (section → article → clause) |

### 8.3 Metadata fields cho filtering/retrieval

Các fields nên index cho **keyword filtering** trong Hybrid RAG:

- `legal_type` — filter theo loại văn bản
- `issuing_authority` — filter theo cơ quan
- `issuance_date` — range filter theo thời gian
- `effect_status` — filter văn bản còn hiệu lực
- `legal_sectors` — filter theo lĩnh vực (cần pre-split multi-value)

### 8.4 LightRAG graph integration

- Sử dụng `merged_relationships.parquet` trực tiếp làm edge list
- Node attributes lấy từ `merged_metadata` (title, legal_type, effect_status)
- Relationship type `Văn bản căn cứ` → dùng làm **primary edge** cho graph traversal
- `Văn bản hết hiệu lực` / `Văn bản sửa đổi` → dùng để **chain versioning** của văn bản

---

_Report generated from: `merged_content.parquet`, `merged_metadata.parquet`, `merged_relationships.parquet`_
""".format(date=datetime.now().strftime("%Y-%m-%d %H:%M"))

OUT_PATH.write_text(md, encoding="utf-8")
print(f"✅ Written to: {OUT_PATH}")
print(f" Size: {OUT_PATH.stat().st_size / 1024:.1f} KB")
