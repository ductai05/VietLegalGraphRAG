# Báo cáo EDA – Dữ liệu văn bản pháp luật Việt Nam (Đã làm sạch)

## 1. Tổng quan

| Thuộc tính                   | Giá trị                                                                                         |
| ---------------------------- | ----------------------------------------------------------------------------------------------- |
| **Lĩnh vực**                 | Pháp luật Việt Nam                                                                              |
| **Mục đích**                 | Xây dựng hệ thống Hybrid RAG (tìm kiếm dense vector + từ khóa + LightRAG) cho hỏi đáp pháp luật |
| **Số lượng văn bản**         | 353.746 (sau khi lọc hiệu lực và loại bỏ trùng lặp)                                             |
| **Số lượng metadata**        | 353.746                                                                                         |
| **Số lượng quan hệ (edges)** | 138.656                                                                                         |
| **Khoảng thời gian**         | 1924-08-25 → 2026-03-25                                                                         |
| **Định dạng lưu trữ**        | Parquet (3 files) – đã được join và lọc                                                         |

> **Ghi chú**: So với dữ liệu thô (564.136 văn bản), tập dữ liệu sạch nhỏ hơn **37,3%** do loại bỏ văn bản hết hiệu lực, trùng lặp và cột rỗng hoàn toàn.

---

## 2. Cấu trúc file sau khi làm sạch

| File                        | Số dòng | Số cột | Dung lượng (ước lượng) |
| --------------------------- | ------- | ------ | ---------------------- |
| `content` (DataFrame)       | 353.746 | 3      | ~5.691 MB              |
| `metadata` (DataFrame)      | 353.746 | 18     | ~161 MB                |
| `relationships` (DataFrame) | 138.656 | 3      | ~5,1 MB                |

- **Cột bị xóa**: `thong_tin_ap_dung` (100% null)
- **Dữ liệu thừa (duplicate ID)**: Đã loại bỏ hoàn toàn (0 duplicate ID)

---

## 3. Schemas

### 3.1 `content`

| Cột       | Kiểu   | Null | Mô tả                                  |
| --------- | ------ | ---- | -------------------------------------- |
| `id`      | Int64  | 0    | Khóa chính, liên kết với `metadata.id` |
| `content` | String | 0    | Toàn bộ nội dung văn bản               |
| `source`  | String | 0    | Nguồn: `legacy`, `legacy+data`, `data` |

### 3.2 `metadata`

| Cột                  | Kiểu   | Null % | Mô tả                                                 |
| -------------------- | ------ | ------ | ----------------------------------------------------- |
| `id`                 | Int64  | 0,0%   | Khóa chính                                            |
| `document_number`    | String | 0,0%   | Số hiệu văn bản (VD: `34/2025/QĐ-UBND`)               |
| `title`              | String | 0,0%   | Tiêu đề                                               |
| `legal_type`         | String | ~0,0%  | Loại văn bản (Quyết định, Công văn, …)                |
| `legal_sectors`      | String | 2,47%  | Lĩnh vực pháp lý (multi-value, phân cách `, `)        |
| `issuing_authority`  | String | 0,04%  | Cơ quan ban hành                                      |
| `issuance_date`      | String | 0,0%   | Ngày ban hành (`YYYY-MM-DD`)                          |
| `effect_date`        | String | 0,0%\* | Ngày có hiệu lực                                      |
| `effectless_date`    | String | 97,57% | Ngày hết hiệu lực (hầu hết null vì đang còn hiệu lực) |
| `effect_status`      | String | 0,0%   | Trạng thái hiệu lực                                   |
| `signers`            | String | 0,12%  | Người ký                                              |
| `nguon_thu_thap`     | String | 90,17% | Nguồn thu thập                                        |
| `ngay_dang_cong_bao` | String | 95,25% | Ngày đăng công báo                                    |
| `nganh`              | String | 89,29% | Ngành                                                 |
| `linh_vuc`           | String | 94,91% | Lĩnh vực                                              |
| `chuc_danh`          | String | 81,98% | Chức danh người ký                                    |
| `pham_vi`            | String | 83,44% | Phạm vi áp dụng                                       |
| `source`             | String | 0,0%   | Nguồn: `legacy`, `legacy+data`, `data`                |

> `effect_date` có 0 null trong thực tế, nhưng do preprocess lọc theo `effect_status` nên toàn bộ văn bản đều có `effect_date` hợp lệ.

### 3.3 `relationships`

| Cột            | Kiểu   | Null | Mô tả                |
| -------------- | ------ | ---- | -------------------- |
| `doc_id`       | Int64  | 0    | Văn bản gốc          |
| `other_doc_id` | Int64  | 0    | Văn bản liên quan    |
| `relationship` | String | 0    | Loại quan hệ pháp lý |

---

## 4. Chất lượng dữ liệu sau làm sạch

### 4.1 Trùng lặp

- **Không còn ID trùng lặp** trong `content` (đã dùng `unique(subset=["id"])`)
- **0 dòng trùng lặp nội dung** với cùng ID – an toàn tuyệt đối

### 4.2 Null fields đáng chú ý

- Các cột có tỉ lệ null > 80% (`effectless_date`, `ngay_dang_cong_bao`, `linh_vuc`, `nguon_thu_thap`, `nganh`, `chuc_danh`, `pham_vi`) được giữ lại nhưng **không nên dùng làm bộ lọc chính**; chỉ dùng khi có dữ liệu.
- Các cột core (`id`, `title`, `document_number`, `legal_type`, `issuance_date`, `effect_status`, `source`) **0% null** – rất tốt.
- Cột `legal_sectors` chỉ null 2,47% → có thể dùng rộng rãi.

### 4.3 ID alignment

- `content.id` và `metadata.id` khớp hoàn toàn: 353.746 IDs.
- `relationships` chứa **40.604 node duy nhất**, tất cả đều tồn tại trong metadata.

---

## 5. Phân tích nội dung (`content`)

### 5.1 Phân bố độ dài (ký tự)

| Bucket       | Số lượng    | %          | Nhận xét                     |
| ------------ | ----------- | ---------- | ---------------------------- |
| < 500 chars  | 560         | 0,16%      | Rất ngắn (có thể là tiêu đề) |
| 500 – 2K     | 75.005      | 21,20%     | Ngắn                         |
| 2K – 5K      | 106.314     | 30,06%     | Trung bình – ngắn            |
| **5K – 20K** | **113.415** | **32,06%** | **Phổ biến nhất**            |
| 20K – 100K   | 53.439      | 15,11%     | Dài                          |
| > 100K       | 5.013       | 1,42%      | Rất dài (hơn 100.000 ký tự)  |

| Thống kê          | Giá trị                   |
| ----------------- | ------------------------- |
| Số lượng          | 353.746                   |
| Độ dài trung bình | 13.030 ký tự              |
| Trung vị (p50)    | 4.749 ký tự               |
| p75               | 13.113 ký tự              |
| Giá trị lớn nhất  | 4.585.077 ký tự (~4,4 MB) |

> **Ý nghĩa cho RAG**: Khoảng 77% văn bản có độ dài từ 500 đến 20.000 ký tự. Cần chunking với `chunk_size ≈ 512–1024 token`, `overlap ≈ 128 token`. Với ~5.000 văn bản dài >100K, nên áp dụng hierarchical chunking (theo điều/khoản).

### 5.2 Phân bố nguồn dữ liệu (`source`)

| Nguồn         | Số lượng | %      |
| ------------- | -------- | ------ |
| `legacy`      | 296.526  | 83,83% |
| `legacy+data` | 36.295   | 10,26% |
| `data`        | 20.925   | 5,91%  |

---

## 6. Phân tích metadata

### 6.1 Loại văn bản (`legal_type`) – top 10

| Loại văn bản         | Số lượng | %      |
| -------------------- | -------- | ------ |
| Quyết định           | 168.708  | 47,70% |
| Công văn             | 122.286  | 34,57% |
| Nghị quyết           | 28.870   | 8,16%  |
| Chỉ thị              | 10.890   | 3,08%  |
| Thông tư             | 9.600    | 2,71%  |
| Kế hoạch             | 3.868    | 1,09%  |
| Thông báo            | 3.044    | 0,86%  |
| Hướng dẫn            | 1.396    | 0,39%  |
| Nghị định            | 1.295    | 0,37%  |
| Quyết định (cá biệt) | 652      | 0,18%  |

> So với dữ liệu thô: tỉ lệ **Công văn** tăng lên (34,6% so với 22,1%) do nhiều công văn còn hiệu lực. **Luật** chỉ còn 212 văn bản (0,06%) – hầu hết luật bị hết hiệu lực hoặc nằm ngoài bộ lọc.

### 6.2 Trạng thái hiệu lực (`effect_status`)

| Trạng thái              | Số lượng | %      |
| ----------------------- | -------- | ------ |
| Còn hiệu lực            | 348.623  | 98,55% |
| Hết hiệu lực một phần   | 5.121    | 1,45%  |
| Ngưng hiệu lực một phần | 2        | <0,01% |

- **Không còn** văn bản "Hết hiệu lực", "Ngưng hiệu lực" hay "Chưa có hiệu lực" – đã bị lọc.
- Vẫn giữ lại một lượng nhỏ văn bản "một phần" (có thể do chúng vẫn còn giá trị tham khảo cho một số điều khoản).

> **Khuyến nghị**: Với mục đích trả lời pháp luật hiện hành, nên ưu tiên lọc `effect_status == 'Còn hiệu lực'` (348k văn bản). Nếu muốn chính xác tuyệt đối, có thể lọc thêm bỏ "Hết hiệu lực một phần".

### 6.3 Phân bố theo năm ban hành (top 20)

| Năm  | Số lượng |
| ---- | -------- |
| 2026 | 2.988    |
| 2025 | 30.672   |
| 2024 | 25.394   |
| 2023 | 22.111   |
| 2022 | 18.623   |
| 2021 | 17.705   |
| 2020 | 16.326   |
| 2019 | 15.778   |
| 2018 | 14.921   |
| 2017 | 13.648   |
| 2016 | 13.334   |
| 2015 | 12.715   |
| 2014 | 11.423   |
| 2013 | 11.279   |
| 2012 | 10.941   |
| 2011 | 10.547   |
| 2010 | 10.365   |
| 2009 | 9.607    |
| 2008 | 10.258   |
| 2007 | 8.480    |

- Tập trung mạnh vào **2015–2025** (chiếm ~70% dữ liệu)
- Văn bản từ trước 2000 vẫn còn khoảng 4.000 văn bản (chủ yếu là các nghị quyết, quyết định còn hiệu lực dài hạn)

### 6.4 Cơ quan ban hành hàng đầu

| Cơ quan               | Số lượng |
| --------------------- | -------- |
| Tổng cục Thuế         | 22.634   |
| Tổng cục Hải quan     | 19.985   |
| Thủ tướng Chính phủ   | 15.184   |
| Văn phòng Chính phủ   | 12.305   |
| Bộ Tài chính          | 11.894   |
| Bộ Xây dựng           | 6.614    |
| Bộ Nông nghiệp & PTNT | 6.427    |
| Bộ Y tế               | 5.434    |
| Bộ Công thương        | 3.399    |
| Thành phố Hồ Chí Minh | 3.828    |

### 6.5 Lĩnh vực pháp lý (`legal_sectors`) – tách multi-value

Sau khi tách chuỗi phân cách bằng `, `, có **1.583 lĩnh vực duy nhất**. Top 10:

| Lĩnh vực              | Số lần xuất hiện |
| --------------------- | ---------------- |
| Bộ máy hành chính     | 92.673           |
| Thuế                  | 50.667           |
| Lệ phí                | 50.667           |
| Phí                   | 51.413           |
| Xuất nhập khẩu        | 29.783           |
| Tài chính nhà nước    | 24.540           |
| Xây dựng – đô thị     | 19.318           |
| Thương mại            | 18.964           |
| Đầu tư                | 15.446           |
| Lao động – tiền lương | 12.765           |

---

## 7. Đồ thị quan hệ (`relationships`)

| Chỉ số                            | Giá trị              |
| --------------------------------- | -------------------- |
| Tổng số cạnh                      | 138.656              |
| Số node nguồn duy nhất (`doc_id`) | 38.183               |
| Tổng số node (src + dst)          | 40.604               |
| Tất cả node đều có metadata       | ✅ Đúng              |
| Bậc trung bình (out-degree)       | 3,63                 |
| Bậc trung vị                      | 2                    |
| Bậc lớn nhất                      | 201 (doc_id = 12979) |

### Phân bố loại quan hệ

| Loại quan hệ                   | Số lượng | %      |
| ------------------------------ | -------- | ------ |
| Văn bản căn cứ                 | 98.479   | 71,03% |
| Văn bản dẫn chiếu              | 12.266   | 8,85%  |
| Văn bản được HD, QĐ chi tiết   | 5.493    | 3,96%  |
| Văn bản HD, QĐ chi tiết        | 5.475    | 3,95%  |
| Văn bản bổ sung                | 4.270    | 3,08%  |
| Văn bản sửa đổi / được sửa đổi | ~1.788   | 1,29%  |
| Văn bản bãi bỏ / được bãi bỏ   | ~736     | 0,53%  |
| Văn bản quy định hết hiệu lực  | 192      | 0,14%  |
| Văn bản hết hiệu lực           | 184      | 0,13%  |
| Khác (liên quan, đình chỉ, …)  | ~10.000  | 7,2%   |

> **Quan trọng**: Loại "Văn bản căn cứ" chiếm 71% – phản ánh mạnh mẽ mạng lưới phụ thuộc pháp lý. Rất giá trị cho graph traversal trong LightRAG.

---

## 8. Đề xuất cho Hybrid RAG Pipeline (cập nhật)

### 8.1 Tiền xử lý (đã hoàn thành)

```python
# Các bước đã thực hiện
content = content.unique(subset=["id"])   # loại duplicate
metadata = metadata.drop("thong_tin_ap_dung")
metadata = metadata[~metadata["effect_status"].isin(INACTIVE_STATUSES)]
# Đồng bộ content & relationships với active_ids
```

**Lưu ý**: Vẫn còn 5.123 văn bản có `effect_status` là "Hết hiệu lực một phần"/"Ngưng hiệu lực một phần". Tuỳ theo yêu cầu nghiệp vụ, có thể lọc tiếp hoặc gắn nhãn trong metadata.

### 8.2 Chiến lược chunking

| Độ dài văn bản | Chiến lược                                     |
| -------------- | ---------------------------------------------- |
| < 2.000 ký tự  | Giữ nguyên document (không chunk)              |
| 2K – 20K       | Chunk 512–1024 token, overlap 128 token        |
| 20K – 100K     | Recursive chunking theo cấu trúc (Điều, Khoản) |
| > 100K         | Hierarchical chunking (Chương → Điều → Khoản)  |

### 8.3 Các trường metadata nên index cho filtering

- `legal_type` – filter theo loại văn bản
- `issuing_authority` – filter theo cơ quan
- `issuance_date` – range filter theo thời gian
- `effect_status` – lọc văn bản còn hiệu lực (hoặc loại bỏ "một phần")
- `legal_sectors` – filter theo lĩnh vực (cần split multi-value)
- `source` – nếu muốn ưu tiên nguồn `data` hoặc `legacy+data`

### 8.4 Tích hợp LightRAG với đồ thị đã làm sạch

- Dùng `relationships` trực tiếp làm edge list (138.656 cạnh)
- Gán node attributes từ `metadata` (title, legal_type, effect_status, issuance_date)
- Ưu tiên sử dụng cạnh **"Văn bản căn cứ"** làm primary edge cho graph traversal
- Các cạnh "Văn bản hết hiệu lực" / "Văn bản sửa đổi" tuy số lượng nhỏ nhưng rất quan trọng để **chain versioning** của văn bản (ví dụ: tìm văn bản mới nhất thay thế)

---

## 9. Kết luận

Dữ liệu sau preprocess đạt chất lượng tốt:

- **Toàn vẹn ID**, không trùng lặp
- **Tập trung vào văn bản còn hiệu lực** (>98%)
- **Đồ thị quan hệ** thu nhỏ nhưng vẫn giữ được cấu trúc căn cứ pháp lý quan trọng
- **Phân bố độ dài** phù hợp với chunking tiêu chuẩn

Hệ thống Hybrid RAG có thể xây dựng trực tiếp trên 353.746 văn bản, với metadata phong phú và đồ thị quan hệ có hướng sẵn sàng cho LightRAG.

---

_Báo cáo được tạo từ kết quả preprocess thực tế – dữ liệu sạch, sẵn sàng cho pipeline._
