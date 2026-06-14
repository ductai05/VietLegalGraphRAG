# PP-OCRv6 Contract Review Demo

Ứng dụng web để:

1. Tải lên một hợp đồng PDF.
2. Render từng trang PDF thành ảnh.
3. Detect dòng bằng PP-OCRv6 medium safetensors và nhận dạng bằng model
   tiếng Việt.
4. Cho phép kiểm tra, sửa văn bản OCR.
5. Gửi văn bản tới Gemini để rà soát các điều khoản cần lưu ý.

Kết quả Gemini chỉ hỗ trợ rà soát ban đầu, không thay thế tư vấn pháp lý.

## Model sử dụng

- Detection: [PaddlePaddle/PP-OCRv6_medium_det_safetensors](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det_safetensors)
- Recognition mặc định: [EasyOCR](https://github.com/JaidedAI/EasyOCR), ngôn ngữ
  `vi,en`
- Recognition dự phòng: [PaddlePaddle/PP-OCRv6_medium_rec_safetensors](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec_safetensors)
- Gemini mặc định: `gemini-3.5-flash`

`PP-OCRv6_medium_det` luôn thực hiện detection. Khi
`OCR_ENGINE=transformers`, detector chạy repository safetensors tương ứng trên
Hugging Face. Mặc định, các box được sắp xếp, thêm lề rồi chuyển cho recognizer
EasyOCR tiếng Việt.

Lý do dùng kiến trúc lai: vocabulary của bản
`PP-OCRv6_medium_rec_safetensors` đã kiểm tra không có nhiều ký tự tiếng Việt
dựng sẵn như `ắ`, `ộ`, `ờ`, `ệ` và cũng không có combining marks. Vì vậy model
không thể trả đúng các dấu này dù confidence cao. Có thể đặt
`OCR_RECOGNITION_BACKEND=paddle` để chạy lại recognizer PP-OCRv6 nguyên bản
khi cần so sánh.

## Kiến trúc

```text
Gradio UI
   |
ContractReviewService
   |-- PDFRenderer (PyMuPDF, xử lý tuần tự từng trang)
   |-- PaddleOCREngine (PP-OCRv6 detector + recognizer cấu hình được)
   |-- GeminiContractAnalyzer (chunk + tổng hợp hợp đồng dài)
   `-- DocumentConsumer port (điểm nối RAG/KG trong tương lai)
```

Backend không phụ thuộc Gradio. `OCRDocument` là schema trung gian gồm trang,
dòng, confidence và polygon. Tab `JSON sẵn sàng cho RAG/KG` hiển thị đúng
schema này; có thể viết thêm một `DocumentConsumer` để index vào Elasticsearch,
Qdrant, Neo4j hoặc pipeline hiện có mà không sửa OCR/UI.

## Yêu cầu

- Windows 10/11 hoặc Linux x64.
- Python 3.10-3.13; khuyến nghị Python 3.12 hoặc 3.13.
- RAM tối thiểu 8 GB, khuyến nghị 16 GB.
- GPU NVIDIA khuyến nghị từ 6 GB VRAM. CPU vẫn chạy được nhưng chậm hơn.
- Internet ở lần đầu để tải model PP-OCRv6 và EasyOCR.

## Cài đặt local trên Windows

Mở PowerShell tại repository:

```powershell
cd app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### Cài PyTorch GPU

Phải cài wheel PyTorch có CUDA trước khi cài requirements. Kiểm tra:

```powershell
nvidia-smi
```

Máy đang phát triển có RTX 3060 6 GB, driver `546.30` và báo CUDA `12.3`.
Lựa chọn tương thích ngay với driver này:

```powershell
python -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu118
```

Hoặc cập nhật NVIDIA driver, sau đó lấy lệnh CUDA mới nhất từ trang
[PyTorch Start Locally](https://pytorch.org/get-started/locally/). Ví dụ wheel
CUDA 12.6:

```powershell
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
```

Không cần cài CUDA Toolkit riêng vì wheel PyTorch đã chứa CUDA runtime cần
thiết. Sau đó cài ứng dụng:

```powershell
python -m pip install -r requirements.txt
```

Xác minh GPU:

```powershell
python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
```

Kết quả đầu tiên phải là `True`. Nếu là `False`, app vẫn tự chuyển sang CPU.

### Cấu hình

```powershell
Copy-Item .env.example .env
```

Các biến thường dùng:

| Biến | Mặc định | Ý nghĩa |
|---|---:|---|
| `OCR_DEVICE` | `auto` | `auto`, `cpu` hoặc `gpu:0` |
| `OCR_RECOGNITION_BACKEND` | `easyocr` | `easyocr` hoặc `paddle` |
| `OCR_EASYOCR_LANGUAGES` | `vi,en` | Danh sách ngôn ngữ recognition |
| `OCR_RECOGNITION_BATCH_SIZE` | `8` | Batch các dòng cho recognizer |
| `OCR_CROP_PADDING_RATIO` | `0.15` | Lề quanh box để không cắt mất dấu |
| `PDF_DPI` | `180` | DPI mặc định để render PDF |
| `MAX_PDF_PAGES` | `50` | Số trang tối đa mỗi tài liệu |
| `MAX_UPLOAD_MB` | `50` | Giới hạn dung lượng upload |
| `OCR_TEXT_SCORE_THRESHOLD` | `0.20` | Bỏ các dòng recognition quá yếu |
| `GEMINI_API_KEY` | trống | Key server-side, không bắt buộc |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Model Gemini mặc định |
| `GEMINI_CHUNK_CHARS` | `30000` | Kích thước mỗi phần hợp đồng |
| `GEMINI_MAX_CHUNKS` | `12` | Số phần tối đa trước khi từ chối |
| `GRADIO_SERVER_NAME` | `127.0.0.1` | Dùng `0.0.0.0` khi deploy |
| `GRADIO_SERVER_PORT` | `7860` | Cổng web |

Không commit `.env`. Có thể không đặt `GEMINI_API_KEY` và nhập key trong ô
password trên giao diện. Key nhập trên UI không được lưu vào JSON OCR.

Theo tài liệu Google hiện tại, nên tạo authorization key mới trong Google AI
Studio. Unrestricted standard key sẽ bị từ chối từ ngày 19/06/2026 và standard
key sẽ ngừng hoạt động trong tháng 09/2026.

### Chạy

```powershell
python main.py
```

Mở [http://127.0.0.1:7860](http://127.0.0.1:7860).

Lần chạy OCR đầu tiên sẽ tải model và lâu hơn. PP-OCRv6 được cache bởi PaddleX;
EasyOCR mặc định cache trong `~/.EasyOCR`.

## Hướng dẫn sử dụng

1. Chọn hợp đồng `.pdf`.
2. Nhập Gemini API key, hoặc để trống nếu đã cấu hình trong `.env`.
3. Giữ DPI `180` cho bản scan thông thường; tăng lên `220-300` khi chữ nhỏ.
4. Chọn số trang cần xử lý.
5. Bấm **OCR và phân tích hợp đồng** để chạy toàn bộ.
6. Hoặc bấm **Chỉ chạy OCR**, sửa text nhận diện nếu cần, rồi bấm
   **Phân tích text hiện tại**.
7. Xem confidence theo dòng và JSON ở các tab bên dưới.

Mẹo:

- DPI cao tăng độ chính xác nhưng tốn VRAM và thời gian.
- Với RTX 3060 6 GB, giữ batch size `1` như cấu hình mặc định.
- Confidence giữa các recognizer không cùng thang đo. Confidence thấp không
  chắc chắn là sai; luôn đối chiếu PDF gốc ở số tiền,
  ngày tháng, mã số và điều khoản phạt.
- PDF có mật khẩu phải được mở khóa trước khi upload.

## Chạy test

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Chạy kèm coverage và yêu cầu tối thiểu 85%:

```powershell
python -m pytest -q `
  --cov=contract_ocr --cov=ui --cov=main `
  --cov-report=term-missing --cov-fail-under=85
```

Chạy integration test với detector PP-OCRv6 và recognizer tiếng Việt thật
(model phải tải được hoặc đã có cache):

```powershell
$env:RUN_OCR_INTEGRATION="1"
python -m pytest -q -m integration
Remove-Item Env:RUN_OCR_INTEGRATION
```

Unit test không gọi Gemini thật. Integration test OCR dùng trang đầu của
`docs/outline.pdf` và có thể chạy GPU hoặc CPU.

Nếu đang đứng tại root repository:

```powershell
app\.venv\Scripts\python.exe -m pytest -c app\pytest.ini app\tests -q
```

## Docker

Build bản CPU:

```bash
docker build -t contract-ocr .
docker run --rm -p 7860:7860 --env-file .env contract-ocr
```

Để cache model qua nhiều lần chạy:

```bash
docker run --rm -p 7860:7860 --env-file .env \
  -v ocr-models:/models contract-ocr
```

Volume `/models` lưu cả cache PaddleX/Hugging Face và EasyOCR.

Với GPU, dùng NVIDIA Container Toolkit và build bằng một PyTorch CUDA runtime
image phù hợp làm `BASE_IMAGE`. Nếu image nền đã có PyTorch CUDA thỏa
`torch>=2.7`, pip sẽ giữ bản đó:

```bash
docker build \
  --build-arg BASE_IMAGE=pytorch/pytorch:<version>-cuda<version>-cudnn9-runtime \
  -t contract-ocr-gpu .

docker run --rm --gpus all -p 7860:7860 \
  --env-file .env -v ocr-models:/models contract-ocr-gpu
```

## Gợi ý deploy và mở rộng

- Đặt `GRADIO_SERVER_NAME=0.0.0.0`.
- Chạy sau Nginx/Caddy và bật HTTPS, authentication, upload limit.
- Lưu Gemini key trong secret manager của cloud, không đưa vào image.
- Mỗi GPU nên chạy một OCR worker; queue hiện khóa inference để tránh nhiều
  request tranh VRAM.
- Khi cần scale ngang, tách `ContractReviewService` thành API/worker và dùng
  Redis, RabbitMQ hoặc cloud queue.
- Thêm adapter triển khai `DocumentConsumer.consume(document)` để đẩy JSON vào
  pipeline RAG/knowledge graph.
- Với hợp đồng rất dài, thay chunking tuần tự bằng retrieval theo điều khoản,
  nhưng không cần thay PDF/OCR schema.

## Cấu trúc thư mục

```text
app/
|-- main.py
|-- ui.py
|-- contract_ocr/
|   |-- config.py
|   |-- models.py
|   |-- pdf.py
|   |-- ocr.py
|   |-- gemini.py
|   |-- prompts.py
|   |-- ports.py
|   `-- service.py
|-- tests/
|-- requirements.txt
|-- requirements-dev.txt
|-- .env.example
`-- Dockerfile
```

## Nguồn tham khảo

- [PP-OCRv6 detector model card](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det_safetensors)
- [PP-OCRv6 recognizer model card](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_rec_safetensors)
- [EasyOCR repository và danh sách ngôn ngữ](https://github.com/JaidedAI/EasyOCR)
- [PaddleOCR general OCR pipeline](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html)
- [Gemini text generation](https://ai.google.dev/gemini-api/docs/text-generation)
- [Gemini API key security](https://ai.google.dev/gemini-api/docs/api-key)
