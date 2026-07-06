# Raw Data

Thư mục này chứa dữ liệu gốc được tải từ các nguồn bên ngoài, trước khi làm sạch và chunking.

## Cấu trúc

```text
raw/
└── vietnamese_legal_documents/
```

## Vai trò

- Lưu bản sao dữ liệu gốc để pipeline có đầu vào tái lập.
- Không chỉnh sửa trực tiếp dữ liệu raw.
- Mọi biến đổi nên được thực hiện qua pipeline và lưu kết quả vào `data/processed/`.

## Lưu ý

Thư mục này bị Git ignore đối với data artifact. Chỉ `README.md` và `.gitkeep` được track để giữ cấu trúc trên remote.
