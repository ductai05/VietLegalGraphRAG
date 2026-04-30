# ⚖️ Vietnamese Legal GraphRAG (Hệ thống Truy xuất Luật Việt Nam)

> Trợ lý ảo AI hỗ trợ tra cứu, diễn giải pháp luật và phân tích hợp đồng tự động, ứng dụng công nghệ **RAG (Retrieval-Augmented Generation)** kết hợp với **Đồ thị Tri thức (Knowledge Graph)**.
> 
> *Đồ án môn Nhập môn Học máy - Trường Đại học Khoa học Tự nhiên, ĐHQG-HCM.*

## 🌟 Giới thiệu
Văn bản pháp luật thường dài dòng, chồng chéo và khó tiếp cận với phần đông người dân, dẫn đến những rủi ro pháp lý khi ký kết hợp đồng hoặc giải quyết tranh chấp. Dự án **Vietnamese Legal GraphRAG** được xây dựng nhằm "bình dân hóa" pháp luật, giúp người dùng tra cứu thông tin nhanh chóng, chính xác và có thể hiểu luật một cách đơn giản nhất mà không tốn kém chi phí.

## ✨ Tính năng chính
- 💬 **Chatbot Pháp lý Tùy chỉnh:** Trả lời các câu hỏi về luật pháp. Người dùng có thể chọn chế độ giải thích *Dễ hiểu* (dành cho người dân) hoặc *Chuyên sâu* (dành cho sinh viên, chuyên viên luật).
- 🔍 **Trích dẫn Minh bạch (Citations):** Không như các chatbot "hộp đen" khác, hệ thống sẽ trích xuất và hiển thị rõ ràng điều khoản, nghị định được dùng làm căn cứ ngay cạnh câu trả lời.
- 📄 **Phân tích Rủi ro Hợp đồng (OCR):** Người dùng chỉ cần tải lên hình ảnh hợp đồng, hệ thống sẽ trích xuất nội dung (PaddleOCR) và chỉ ra các điều khoản bất lợi/rủi ro tiềm ẩn.

## 🛠️ Kiến trúc & Công nghệ
- **Mô hình Ngôn ngữ (LLMs):** Gemini, Qwen.
- **Embedding Models:** PhoBERT, BGE-M3, vietlegal-harrier.
- **GraphRAG Framework:** LangChain, LightRAG.
- **Xử lý ảnh (OCR):** PaddleOCR.
- **Backend & Cơ sở dữ liệu:** Python, FastAPI, cơ sở dữ liệu đồ thị **Neo4j**.
- **Frontend:** TypeScript, Next.js.

## 🗄️ Dữ liệu & Đồ thị Tri thức
Hệ thống sử dụng bộ dữ liệu `vietnamese-legal-documents` (>518,000 văn bản) từ HuggingFace. Để giải quyết tính liên kết chồng chéo của luật Việt Nam, dữ liệu được mô hình hóa thành Đồ thị tri thức (Knowledge Graph) với 3 phân tầng ưu tiên:
1. **Tầng 1 (Nền tảng):** Hiến pháp, Bộ luật, Văn bản hợp nhất,...
2. **Tầng 2 (Hướng dẫn thi hành):** Nghị định, Thông tư, Quyết định,...
3. **Tầng 3 (Chuyên ngành/Đối ngoại):** Điều ước, Hiệp định, Quy chế,...

## 👨‍💻 Thành viên phát triển (Team)
- Đinh Đức Anh Khoa (23122001)
- Nguyễn Lê Hoàng Trung (23122004)
- Đinh Đức Tài (23122013)
- Lê Hoàng Minh Huy (23122033)
- Nguyễn Trần Trung Kiên (23122038)

**Giảng viên hướng dẫn:** TS. Bùi Tiến Lên

## Cấu trúc thư mục
\\	ext
[ML]_VietLegalGraphRAG/
├── src/                # Mã nguồn chính của dự án (pipeline, services, apps, utils)
├── notebooks/          # Jupyter notebooks cho EDA và thử nghiệm
├── experiments/        # Các scripts chạy thử nghiệm mô hình
├── scripts/            # Script tự động hóa cài đặt (setup, tải dữ liệu)
├── data/               # Dữ liệu dự án
│   ├── raw/            # Dữ liệu gốc (chưa qua xử lý)
│   └── processed/      # Dữ liệu đã xử lý
├── models/             # Chứa model checkpoints và configurations
├── logs/               # File log xuất ra khi chạy hệ thống
├── main.py             # Entrypoint chính để chạy các module
├── README.md
└── requirements.txt
\## 🛠 Hướng dẫn Cài đặt
Dự án cung cấp các script tự động thiết lập môi trường (ưu tiên sử dụng Conda với Python 3.12) và tải dataset từ HuggingFace.
### 1. Cài đặt toàn bộ (Khuyên dùng)
Chạy script tổng hợp dưới đây trên PowerShell để tự tạo môi trường Conda (hoặc venv), cài đặt thư viện và tải dữ liệu:
\\powershell
.\scripts\setup_all.ps1
\### 2. Cài đặt thủ công từng bước
**Bước 2.1: Tạo môi trường ảo (ví dụ với Conda)**
\\ash
conda create -n vlegal_env python=3.12 -y
conda activate vlegal_env
pip install -r requirements.txt
pip install huggingface_hub
\**Bước 2.2: Tải dữ liệu từ HuggingFace**
Dữ liệu sẽ được tự động tải vào \data/raw/vietnamese-legal-documents\.
\\ash
python scripts/download_data.py
\## 🚀 Hướng dẫn Sử dụng
Chạy \main.py\ với các tham số task tương ứng (ví dụ: \data_prep\, \	rain\, \infer\):
\\ash
python main.py --task data_prep
\

## Cấu trúc thư mục

```text
[ML]_VietLegalGraphRAG/
├── src/                # Mã nguồn chính của dự án (pipeline, services, apps, utils)
├── notebooks/          # Jupyter notebooks cho EDA và thử nghiệm
├── experiments/        # Các scripts chạy thử nghiệm mô hình
├── scripts/            # Script tự động hóa cài đặt (setup, tải dữ liệu)
├── data/               # Dữ liệu dự án
│   ├── raw/            # Dữ liệu gốc (chưa qua xử lý)
│   └── processed/      # Dữ liệu đã xử lý
├── models/             # Chứa model checkpoints và configurations
├── logs/               # File log xuất ra khi chạy hệ thống
├── main.py             # Entrypoint chính để chạy các module
├── README.md
└── requirements.txt
```

## 🛠 Hướng dẫn Cài đặt

Dự án cung cấp các script tự động thiết lập môi trường (ưu tiên sử dụng Conda với Python 3.12) và tải dataset từ HuggingFace.

### 1. Cài đặt toàn bộ (Khuyên dùng)
Chạy script tổng hợp dưới đây trên PowerShell để tự tạo môi trường Conda (hoặc venv), cài đặt thư viện và tải dữ liệu:
```powershell
.\scripts\setup_all.ps1
```

### 2. Cài đặt thủ công từng bước

**Bước 2.1: Tạo môi trường ảo (ví dụ với Conda)**
```bash
conda create -n vlegal_env python=3.12 -y
conda activate vlegal_env
pip install -r requirements.txt
pip install huggingface_hub
```

**Bước 2.2: Tải dữ liệu từ HuggingFace**
Dữ liệu sẽ được tự động tải vào `data/raw/vietnamese-legal-documents`.
```bash
python scripts/download_data.py
```

## 🚀 Hướng dẫn Sử dụng
Chạy `main.py` với các tham số task tương ứng (ví dụ: `data_prep`, `train`, `infer`):
```bash
python main.py --task data_prep
```