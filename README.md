# ⚖️ Vietnamese Legal GraphRAG (Hệ thống Truy xuất Luật Việt Nam)

> Trợ lý ảo AI hỗ trợ tra cứu, diễn giải pháp luật và phân tích hợp đồng tự động, ứng dụng công nghệ **RAG (Retrieval-Augmented Generation)** kết hợp với **Đồ thị Tri thức (Knowledge Graph)**.
> 
> *Đồ án môn Nhập môn Học máy - Trường Đại học Khoa học Tự nhiên, ĐHQG-HCM.*

## 🌟 Giới thiệu
Văn bản pháp luật thường dài dòng, chồng chéo và khó tiếp cận với phần đông người dân, dẫn đến những rủi ro pháp lý khi ký kết hợp đồng hoặc giải quyết tranh chấp. Dự án **Vietnamese Legal GraphRAG** được xây dựng nhằm "bình dân hóa" pháp luật, giúp người dùng tra cứu thông tin nhanh chóng, chính xác và có thể hiểu luật một cách đơn giản nhất mà không tốn kém chi phí.

## ✨ Tính năng chính
- 💬 **Chatbot Pháp lý Tùy chỉnh:** Trả lời các câu hỏi về luật pháp. Người dùng có thể chọn chế độ giải thích *Dễ hiểu* (dành cho người dân) hoặc *Chuyên sâu* (dành cho sinh viên, chuyên viên luật).
- 🔍 **Trích dẫn Minh bạch (Citations):** Không như các chatbot "hộp đen" khác, hệ thống sẽ trích xuất và hiển thị rõ ràng điều khoản, nghị định được dùng làm căn cứ ngay cạnh câu trả lời.
- 📄 **Phân tích Rủi ro Hợp đồng (OCR):** Người dùng chỉ cần tải lên hình ảnh hợp đồng, hệ thống sẽ trích xuất nội dung bằng Google Cloud Vision OCR và chỉ ra các điều khoản bất lợi/rủi ro tiềm ẩn.

## 🛠️ Kiến trúc & Công nghệ
- **Mô hình Ngôn ngữ (LLMs):** Gemini, Qwen.
- **Embedding Models:** PhoBERT, BGE-M3, vietlegal-harrier.
- **GraphRAG Framework:** LangChain, LightRAG.
- **Xử lý ảnh (OCR):** Google Cloud Vision OCR.
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

## 📁 Cấu trúc thư mục

```text
VietLegalGraphRAG/
│
├── pipeline/                          # AI/Data pipeline - từng bước xử lý
│   ├── 01_data_download/              #   Tải dữ liệu từ HuggingFace
│   │   ├── requirements.txt           #   Dependencies riêng (chỉ huggingface_hub)
│   │   ├── download_data.py           #   Script tải data
│   │   └── README.md
│   ├── 02_eda/                        #   Exploratory Data Analysis
│   ├── 03_preprocessing/              #   Tiền xử lý dữ liệu
│   ├── 05_graph/                      #   Xây dựng Knowledge Graph
│   ├── 05_embedding/                  #   Tạo vector embeddings
│   ├── 06_training/                   #   Huấn luyện mô hình
│   └── 07_evaluation/                 #   Đánh giá mô hình
│
├── docs/                              # Tài liệu, báo cáo (LaTeX, PDF)
│
├── app/                               # Web Application source
│
├── data/                              # Dữ liệu dự án
│   ├── raw/                           #   Dữ liệu gốc (tải từ HuggingFace)
│   └── preprocessed/                  #   Dữ liệu đã tiền xử lý
│
├── .gitignore
├── LICENSE
└── README.md
```

## 🎯 MVP Runtime Scope

The MVP runtime uses **Elasticsearch Cloud** for both dense and sparse retrieval, **Neo4j on a dedicated VPS** for the legal knowledge graph, **Google Cloud Vision OCR** as an external managed OCR service, and **FastAPI** for the backend contract consumed by the frontend.

Qdrant references in older embedding notes are historical and are not required for the MVP runtime. Frontend code should call the backend API only and should not call Elasticsearch, Neo4j, reranker models or LLM providers directly.

Local PaddleOCR is no longer part of the MVP runtime. OCR authentication uses a Google Service Account JSON credential that must not be committed to git.

LightRAG is only the orchestration layer. It does not replace Elasticsearch retrieval. The MVP answer flow is: user query -> intent detection -> hybrid Elasticsearch retrieval (dense + sparse) -> RRF -> optional rerank -> document resolution -> optional one-hop Neo4j graph expansion -> context assembly -> answer -> citation + trace.

## 📋 MVP Decision Log

Decisions recorded during Phase 0 scope freeze, per the MVP phase backlog specification.

### `Chunk` vs `Article` Neo4j Label

- **Decision:** Keep `Chunk` as the internal Neo4j label. The API layer maps `Chunk` to `Article` in response fields when the semantic context requires it (document article traversal, section references).
- **Rationale:** Renaming the label requires a full graph migration with no functional benefit at this stage. A clean rename can follow after the demo.
- **Risk:** Internal code must consistently refer to "chunk" in graph queries and "article" in API responses, creating a mapping burden. Mitigated by keeping the mapping logic in one place (GraphRetriever and schemas).

### Graph Size Strategy

- **Decision:** Prepare both a subset smoke graph path and a full-corpus graph path. The demo uses the subset graph.
- **Subset scope:** Filtered by top legal types (Luật, Nghị định, Thông tư) or a document count limit manageable on local hardware (~10K documents).
- **Full graph:** Available if the demo machine has sufficient RAM and SSD for the complete corpus (>518K documents). Not the default demo path.
- **Rationale:** Full Neo4j import may exceed small local machines. A subset ensures reproducible demo behavior regardless of presenter hardware.

## 🛠 Hướng dẫn Cài đặt

Mỗi bước trong `pipeline/` có **requirements.txt riêng**, bạn chỉ cần cài đặt dependencies cho bước cần chạy.

### Tải dữ liệu

```bash
# Di chuyển vào thư mục bước tải data
cd pipeline/01_data_download

# Cài đặt dependencies (chỉ cần huggingface_hub)
pip install -r requirements.txt

# Chạy script tải data
python download_data.py
```

Dữ liệu sẽ được tải vào `data/raw/vietnamese-legal-documents/`.
