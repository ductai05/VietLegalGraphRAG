# 📂 Preprocessed Data

Thư mục này chứa **dữ liệu đã qua tiền xử lý** (preprocessed data), sẵn sàng để đưa vào các bước tiếp theo của pipeline.

## Mục đích

- Lưu trữ dữ liệu đã được làm sạch, chuẩn hóa, hoặc chuyển đổi định dạng từ dữ liệu thô (`data/raw/`).
- Đầu ra ở đây là đầu vào cho các bước xây dựng Knowledge Graph và Embedding.

## Lưu ý

- **Thư mục này bị Git ignore** - các file dữ liệu sẽ **không** được commit lên repository.
- Dữ liệu trong thư mục này được tạo tự động bởi các script trong pipeline. Không nên chỉnh sửa thủ công.
- Nếu cần tái tạo dữ liệu, hãy chạy lại pipeline từ bước tiền xử lý.
