# VietLegalGraphRAG

VietLegalGraphRAG là hệ thống hỏi đáp pháp luật tiếng Việt dựa trên Retrieval-Augmented Generation kết hợp truy xuất ngữ nghĩa kết hợp tìm kiếm từ khóa, kiểm tra quan hệ văn bản bằng đồ thị tri thức và giao diện hội thoại Open WebUI. Dự án được xây dựng trong bối cảnh học thuật nhằm khảo sát cách kết hợp tìm kiếm ngữ nghĩa, tìm kiếm từ khóa, reranking, tri thức đồ thị và mô hình ngôn ngữ lớn cho bài toán tra cứu văn bản pháp luật Việt Nam.

> Lưu ý: hệ thống chỉ hỗ trợ tra cứu và giải thích thông tin pháp luật từ ngữ cảnh được truy xuất. Kết quả sinh ra không thay thế tư vấn pháp lý chính thức từ luật sư, cơ quan nhà nước hoặc chuyên gia có thẩm quyền.

Demo Video: [![VietLegalGraphRAG Demo](https://img.youtube.com/vi/CkdYwaeIEU8/maxresdefault.jpg)](https://www.youtube.com/watch?v=CkdYwaeIEU8)

## Thành viên thực hiện

- Đinh Đức Anh Khoa, 23122001
- Nguyễn Lê Hoàng Trung, 23122004
- Đinh Đức Tài, 23122013
- Lê Hoàng Minh Huy, 23122033
- Nguyễn Trần Trung Kiên, 23122038

Giảng viên hướng dẫn: TS. Bùi Tiến Lên

Đơn vị: Trường Đại học Khoa học Tự nhiên, Đại học Quốc gia Thành phố Hồ Chí Minh

## Mục tiêu

Dự án hướng tới ba mục tiêu chính:

1. Xây dựng một quy trình truy xuất pháp luật có căn cứ, có khả năng trả lời câu hỏi bằng tiếng Việt và hiển thị nguồn tham chiếu minh bạch.
2. Kết hợp Elasticsearch và Neo4j để vừa tìm các đoạn văn bản liên quan, vừa kiểm tra quan hệ hiệu lực, thay thế, dẫn chiếu hoặc liên quan giữa các văn bản.
3. Tích hợp hệ thống RAG vào Open WebUI để người dùng có thể tương tác qua giao diện chat, sử dụng citation inline dạng `[1]`, `[2]` và xem chi tiết nguồn trong Sources modal.

## Phạm vi chức năng

### Đã triển khai

- Hỏi đáp pháp luật tiếng Việt dựa trên các đoạn văn bản được truy xuất.
- Truy xuất lai qua Elasticsearch, gồm dense retrieval và sparse retrieval.
- Hợp nhất kết quả bằng RRF, sau đó hỗ trợ rerank tùy cấu hình.
- Kiểm tra và mở rộng ngữ cảnh qua Neo4j knowledge graph.
- Cảnh báo khi văn bản có dấu hiệu hết hiệu lực, bị thay thế hoặc là phiên bản cũ, nếu thông tin này có trong ngữ cảnh.
- Tích hợp Open WebUI bằng `pipe.py` và model `vietlegal_rag`.
- Citation có cấu trúc qua Open WebUI Sources và citation modal.
- Tùy chọn LangGraph ReAct agent để gọi công cụ truy xuất, kiểm tra hiệu lực và tìm đường dẫn nguồn chính thống.
- OCR qua Google Cloud Vision cho luồng xử lý tài liệu, khi được cấu hình.

### Ngoài phạm vi mặc định

- Hệ thống không tự xác nhận tính hiện hành của mọi văn bản nếu dữ liệu đồ thị hoặc metadata hiệu lực chưa đầy đủ.
- Hệ thống không tự tạo căn cứ pháp lý ngoài corpus đã lập chỉ mục.
- Hệ thống không bảo đảm phù hợp cho quyết định pháp lý có rủi ro cao nếu chưa có kiểm chứng chuyên môn.

## Kiến trúc tổng quan

Luồng trả lời mặc định:

```text
User query
  -> Open WebUI
  -> VietLegal RAG Pipe
  -> Query schema and retrieval request
  -> Elasticsearch hybrid retrieval
  -> RRF and optional reranking
  -> Neo4j graph expansion and document resolution
  -> Context assembly
  -> LLM or extractive answer service
  -> Structured citations emitted to Open WebUI
```

Các thành phần chính:

| Thành phần | Vai trò |
|-----------|---------|
| Open WebUI | Giao diện hội thoại, quản lý model, system prompt, citation modal |
| `src/vietlegal_rag` | Gói Python chứa dịch vụ retrieval, graph, rerank, answer, agent và pipe |
| Elasticsearch | Lưu chỉ mục hybrid gồm văn bản, sparse payload và dense vector |
| Neo4j | Lưu đồ thị tri thức pháp luật và quan hệ giữa văn bản |
| ONNX hoặc Hugging Face embedding | Sinh vector truy vấn cho dense retrieval |
| VoyageAI hoặc Jina reranker | Rerank ứng viên, nếu bật |
| Google Cloud Vision | OCR tài liệu hoặc hình ảnh, nếu bật |
| OpenAI-compatible LLM | Sinh câu trả lời tự nhiên, nếu `LLM_PROVIDER=openai-compatible` |

## Citation và system prompt

Hệ thống dùng hai lớp hướng dẫn:

- System prompt cấp Open WebUI model hoặc chat, được chèn vào request trước khi pipe chạy.
- Prompt vận hành nội bộ trong RAG và agent, dùng để ràng buộc truy xuất, kiểm tra hiệu lực và citation.

Trong cấu hình hiện tại, pipe đọc system message từ Open WebUI và truyền xuống `RetrievalRequest.llm.system_prompt`. Luồng RAG thường dùng prompt này khi gọi LLM, còn luồng agent ghép prompt này với quy trình bắt buộc của agent để không làm mất các bước truy xuất và kiểm tra hiệu lực.

Quy ước trả lời:

- Mỗi nhận định pháp lý quan trọng nên có citation inline dạng `[1]`, `[2]`.
- Không sinh khối "Căn cứ pháp lý" thủ công trong nội dung chat.
- Chi tiết văn bản, đoạn trích và metadata nguồn được hiển thị qua Sources và citation modal của Open WebUI.

## Dữ liệu và đồ thị tri thức

Dự án sử dụng dữ liệu văn bản pháp luật tiếng Việt được xử lý qua các bước tiền xử lý, chunking, embedding và xây dựng đồ thị. README này không phân phối lại dữ liệu nguồn hoặc credential truy cập dịch vụ bên ngoài.

Các nhóm dữ liệu trung gian thường gặp:

```text
data/
  raw/                         Dữ liệu gốc, không nên commit nếu dung lượng lớn
  preprocessed/                Dữ liệu đã làm sạch và chuẩn hóa
  retrieval/
    sparse/                    Payload sparse hoặc BM25
    dense/                     Dense vectors và metadata
    graph/                     CSV nodes và edges cho Neo4j
```

Đồ thị tri thức được dùng để biểu diễn các quan hệ như văn bản thay thế, bị thay thế, hướng dẫn, dẫn chiếu hoặc liên quan. Khi graph retrieval được bật, hệ thống có thể bổ sung ngữ cảnh từ các nút lân cận và dùng document resolver để cảnh báo hiệu lực.

## Cấu trúc thư mục

```text
VietLegalGraphRAG/
  data/                         Dữ liệu và artifact xử lý cục bộ
  docs/                         Tài liệu học thuật, báo cáo và phụ lục
  onnx_model/                   Model ONNX cho embedding nếu dùng provider ONNX
  pipeline/
    01_eda/                     Phân tích dữ liệu ban đầu
    02_preprocessing/           Làm sạch, chuẩn hóa và chunking
    03_embeddings/              Sparse và dense embedding
    04_graph/                   Xây dựng artifact đồ thị tri thức
    05_evaluation/              Đánh giá retrieval, graph và LLM
  src/
    infra/                      Docker Compose, Dockerfile, script triển khai
    open-webui/                 Open WebUI đã tích hợp VietLegal RAG
    vietlegal_rag/              Gói Python runtime của hệ thống RAG
  tests/                        Bộ kiểm thử đơn vị và tích hợp
  README.md
  requirements.txt
  pyproject.toml
```

Bộ dữ liệu và model ONNX được đính kèm tại: https://drive.google.com/drive/folders/1m6yT2irl6zHuwGDwTdcdesHTpstWys4Y?usp=sharing

## Yêu cầu hệ thống

Khuyến nghị cho môi trường phát triển:

- Python 3.11 trở lên.
- Docker và Docker Compose.
- Elasticsearch 8.x hoặc Elastic Cloud.
- Neo4j 5.x, có thể chạy trên VPS hoặc môi trường riêng.
- Credential Google Cloud Vision nếu dùng OCR.
- API key cho LLM provider nếu dùng câu trả lời sinh bởi mô hình ngôn ngữ.
- API key cho reranker nếu bật VoyageAI hoặc Jina.
- Model embedding ONNX trong `onnx_model/` nếu cấu hình `EMBEDDING_PROVIDER=onnx`.

## Cài đặt nhanh bằng Docker Compose

1. Sao chép file môi trường:

```bash
cp src/infra/.env.example src/infra/.env
```

2. Điền các biến quan trọng trong `src/infra/.env`:

```dotenv
WEBUI_ADMIN_EMAIL=admin@vietlegal.local
WEBUI_ADMIN_PASSWORD=<strong-password>
WEBUI_SECRET_KEY=<random-secret>

ELASTICSEARCH_URL=<elastic-url>
ELASTICSEARCH_API_KEY=<elastic-api-key>
ELASTICSEARCH_INDEX=vietlegal_chunks_hybrid_v1
ELASTICSEARCH_ALIAS=vietlegal_chunks

NEO4J_URI=bolt://<host>:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<neo4j-password>

EMBEDDING_PROVIDER=onnx
EMBEDDING_ONNX_MODEL_PATH=/app/onnx_model/model.onnx
EMBEDDING_ONNX_TOKENIZER_PATH=/app/onnx_model/tokenizer.json

LLM_PROVIDER=extractive
```

3. Khởi chạy Open WebUI tích hợp VietLegal RAG:

```bash
docker compose --env-file src/infra/.env -f src/infra/docker-compose.yml up --build
```

4. Truy cập giao diện:

```text
http://localhost:8080
```

Sau khi đăng nhập, chọn model `VLGR` hoặc `vietlegal_rag` trong danh sách model để sử dụng hệ thống hỏi đáp pháp luật.

## Cài đặt gói RAG cho phát triển cục bộ

Nếu chỉ phát triển hoặc kiểm thử gói `vietlegal_rag`:

```bash
python -m pip install -r requirements.txt
python -m pip install -e src/vietlegal_rag
```

Một số kiểm thử yêu cầu dịch vụ bên ngoài hoặc artifact dữ liệu đã chuẩn bị. Khi chưa có Elasticsearch, Neo4j hoặc credential đầy đủ, chỉ nên chạy nhóm test không phụ thuộc hạ tầng.

```bash
python -m pytest tests -q --tb=short
```

## Pipeline dữ liệu

Pipeline được chia theo giai đoạn để dễ tái lập và đánh giá:

1. `pipeline/01_eda`: khảo sát dữ liệu và thống kê ban đầu.
2. `pipeline/02_preprocessing`: làm sạch văn bản, chuẩn hóa metadata và chia đoạn.
3. `pipeline/03_embeddings`: tạo sparse payload và dense vector.
4. `pipeline/04_graph`: xây dựng nodes, edges và artifact import Neo4j.
5. `pipeline/05_evaluation`: đánh giá retrieval, rerank, graph và chất lượng trả lời.

Artifact Elasticsearch hybrid thường có dạng:

```text
data/retrieval/
  sparse/bm25_v0.1/sparse_payload.parquet
  dense/vnlegal_lal_v0.1/
    manifest.json
    payload/*.parquet
    vectors/*.npy
```

Import Elasticsearch:

```bash
python src/infra/scripts/import_elasticsearch_hybrid.py \
  --env-file src/infra/production.env \
  --recreate \
  --index vietlegal_chunks_hybrid_v1 \
  --alias vietlegal_chunks
```

Import Neo4j trên VPS:

```bash
bash src/infra/scripts/import_neo4j_droplet.sh \
  --host <DROPLET_IP> \
  --user root \
  --source data/retrieval/graph/kg_v0.1 \
  --neo4j-password "<neo4j-password>" \
  --recreate
```

Lệnh `--recreate` có tính phá hủy với database Neo4j đích. Chỉ sử dụng khi cần import lại toàn bộ graph.

## Cấu hình runtime quan trọng

| Biến | Ý nghĩa |
|------|---------|
| `ELASTICSEARCH_URL` | Endpoint Elasticsearch hoặc Elastic Cloud |
| `ELASTICSEARCH_API_KEY` | API key truy cập Elasticsearch |
| `ELASTICSEARCH_INDEX` | Tên index vật lý |
| `ELASTICSEARCH_ALIAS` | Alias runtime cho truy xuất |
| `EMBEDDING_PROVIDER` | `hf` hoặc `onnx` |
| `EMBEDDING_MODEL` | Model embedding dùng cho truy vấn |
| `NEO4J_URI` | URI kết nối Neo4j |
| `NEO4J_PASSWORD` | Mật khẩu Neo4j |
| `RERANK_PROVIDER` | `voyage`, `jina` hoặc `noop` |
| `LLM_PROVIDER` | `extractive` hoặc `openai-compatible` |
| `LLM_BASE_URL` | Base URL cho OpenAI-compatible provider |
| `AGENT_ENABLED` | Bật hoặc tắt LangGraph ReAct agent |
| `WEB_SEARCH_PROVIDER` | `exa` hoặc `none` cho tìm URL nguồn |
| `GOOGLE_APPLICATION_CREDENTIALS` | Đường dẫn credential Google Vision |

Không commit các file `.env`, credential JSON, API key, database dump hoặc artifact dữ liệu lớn.

## Triển khai production

Production sử dụng Open WebUI container và kết nối tới Elasticsearch, Neo4j, credential OCR và model embedding qua biến môi trường. Neo4j được quản lý riêng và không nằm trong compose app mặc định.

Khởi chạy stack production:

```bash
docker network create vietlegal_net 2>/dev/null || true
docker compose --env-file /opt/vietlegal/env/production.env \
  -f src/infra/docker-compose.production.yml up -d
```

Tài liệu chi tiết hơn nằm tại `src/infra/README.md`.

## Kiểm thử và đánh giá

Các nhóm kiểm thử trong `tests/` bao gồm:

- Kiểm thử chunking và stable IDs.
- Kiểm thử embedding service.
- Kiểm thử Elasticsearch retrieval và ingest.
- Kiểm thử document resolver và graph behavior.
- Kiểm thử agent service và web search service.
- Kiểm thử cấu hình hạ tầng.

Chạy toàn bộ test:

```bash
python -m pytest tests -q --tb=short
```

Một số test có thể cần artifact dữ liệu hoặc dịch vụ ngoài. Khi chạy trong môi trường tối giản, cần thiết lập biến môi trường hoặc bỏ qua nhóm test tích hợp.

## Chuẩn trả lời của hệ thống

Hệ thống được cấu hình để:

- Trả lời bằng tiếng Việt.
- Dựa trên ngữ cảnh truy xuất, không tự bịa căn cứ.
- Gắn citation inline dạng `[1]`, `[2]` cho các nhận định pháp lý quan trọng.
- Không tự tạo danh sách nguồn trong thân câu trả lời.
- Hiển thị nguồn qua Open WebUI Sources và citation modal.
- Cảnh báo khi văn bản có dấu hiệu hết hiệu lực, bị thay thế hoặc là phiên bản cũ.
- Nói rõ khi không đủ căn cứ để kết luận.

## Giấy phép

Mã nguồn được phân phối theo giấy phép trong file `LICENSE`. Việc sử dụng dữ liệu pháp luật, credential dịch vụ ngoài hoặc model bên thứ ba cần tuân thủ điều khoản tương ứng của từng nguồn.

## Trích dẫn học thuật

Nếu sử dụng dự án này trong báo cáo hoặc nghiên cứu, vui lòng trích dẫn tên dự án, nhóm thực hiện, đơn vị đào tạo và thời điểm truy cập repository. Khi công bố kết quả thực nghiệm, cần mô tả rõ phiên bản dữ liệu, cấu hình retrieval, cấu hình graph, mô hình embedding, mô hình sinh và bộ tiêu chí đánh giá.
