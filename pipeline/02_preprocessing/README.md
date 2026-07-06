# 🔧 Bước 3: Tiền xử lý dữ liệu (Preprocessing)

Thư mục này chịu trách nhiệm biến đổi dữ liệu thô từ `data/raw` thành dạng dữ liệu hợp nhất, sạch sẽ và sẵn sàng đưa vào cơ sở dữ liệu vector.

Quá trình tiền xử lý bao gồm 3 bước chính:

## Bước 3.1: Hợp nhất Dữ liệu (Merge Data & Legacy)

Tập `data` chính có chất lượng cao (16 cột tiếng Việt) nhưng bị thiếu hàng trăm ngàn văn bản so với tập `legacy` (bao gồm 449 văn bản cốt lõi như Hiến pháp, Bộ luật, Luật). Do đó, yêu cầu bắt buộc là gộp 2 tập này thành một nguồn duy nhất (Single Source of Truth).

- **Quy tắc gộp:**
  - Lấy tập `data/metadata.parquet` và `data/content.parquet` làm gốc.
  - Quét tập `legacy` và tìm các `id` **không có** trong `data`.
  - Với các văn bản thiếu này, ánh xạ các cột tiếng Anh của `legacy` sang tiếng Việt để khớp với schema của `data` (VD: `legal_type` $\rightarrow$ `loai_van_ban`, `issuance_date` $\rightarrow$ `ngay_ban_hanh`). Các cột không có sẽ điền `NULL`.
  - Lấy cột `content` (text thuần) của `legacy`, bọc trong một thẻ HTML đơn giản (VD: `<p>...</p>`) và gán vào cột `content_html` để gộp vào tập content.
- Đầu ra: `data/preprocessed/merged_metadata.parquet` và `data/preprocessed/merged_content.parquet`.

## Bước 3.2: EDA Cơ bản trên Tập Hợp Nhất

Sau khi có được tập dữ liệu hợp nhất (khoảng hơn 500,000 dòng), bắt buộc phải thực hiện các bước EDA cơ bản để xác nhận tính đúng đắn của phép gộp:

- **Kiểm tra Schema & Row Counts**: Xác nhận số lượng văn bản, không có ID trùng lặp.
- **Data Quality**: Đánh giá tỷ lệ NULL sau khi gộp.
- **Column Stats & Categorical Distributions**: Chạy thống kê phân bố (như đã làm ở Bước 2) trên cột `loai_van_ban`, `tinh_trang_hieu_luc` để đảm bảo không bị sai lệch cấu trúc dữ liệu sau khi map từ tiếng Anh sang tiếng Việt.

## Bước 3.3: Làm sạch và Xử lý Text

- Xử lý các văn bản trong cột `content_html`:
  - Loại bỏ các thẻ HTML (strip tags) để thu được plain text.
  - Chuẩn hóa Unicode tiếng Việt (chuyển về Unicode dựng sẵn).
  - Loại bỏ các ký tự đặc biệt vô nghĩa.
  - Chunking (chia nhỏ văn bản) nếu cần thiết để chuẩn bị cho quá trình nhúng (embedding).

## Bước 3.4: Thực hiện `preprocess_merged_data.ipynb`

# Reproduction

Bước 1: Chạy được `raw_eda.ipynb` trong `02_eda`

Bước 2: Upload `merge_clean_dataset.py` lên kaggle và chạy

Bước 3: Upload `preprocess_merged_data.ipynb` lên kaggle và chạy

Bước 4 (Optional): Chạy `02_eda/cleaned_eda.ipynb`
