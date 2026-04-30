# 📂 Raw Data

Thư mục này chứa **dữ liệu thô** (raw data) được thu thập từ các nguồn pháp luật Việt Nam.

## Mục đích

- Lưu trữ dữ liệu gốc, chưa qua xử lý (file `.parquet`).
- Dữ liệu ở đây là đầu vào cho các bước tiền xử lý (preprocessing) trong pipeline.

## Lưu ý

- **Thư mục này bị Git ignore** - các file dữ liệu sẽ **không** được commit lên repository.
- Để tải dữ liệu về máy, vui lòng chạy script: `pipeline/01_data_download/download_data.py`.
- Không chỉnh sửa trực tiếp dữ liệu trong thư mục này. Mọi biến đổi nên được thực hiện qua pipeline và lưu kết quả vào `data/preprocessed/`.
