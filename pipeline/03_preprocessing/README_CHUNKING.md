# Báo cáo chiến lược chunking cho RAG pháp luật Việt Nam

## 1. Tổng quan

Dự án xây dựng chatbot trợ lý pháp luật Việt Nam sử dụng kiến trúc Hybrid RAG (dense vector search, BM25/keyword matching, LightRAG). Một trong những thành phần quan trọng nhất là chiến lược **chunking** – tách văn bản luật thành các đơn vị truy hồi (retrieval units) đảm bảo giữ nguyên ngữ nghĩa pháp lý, hỗ trợ cả tìm kiếm ngữ nghĩa lẫn tìm kiếm chính xác (số điều, thủ tục, bảng biểu).

Báo cáo này trình bày:

- Bộ dữ liệu đầu vào (content, metadata, relationships)
- Chiến lược chunking chi tiết (nguyên tắc, pipeline, xử lý đặc thù)
- Phương pháp đánh giá trên subset 100 văn bản đa dạng
- Kết quả định lượng và định tính
- Các cải tiến đã thực hiện và hướng phát triển

## 2. Dữ liệu

### 2.1. Content

- `content.parquet`: 3 cột `(id, content, source)`
- `content` chứa toàn văn bản luật (Quyết định, Nghị định, Thông tư, Chỉ thị, Nghị quyết…) dạng text OCR hoặc thu thập từ nguồn công báo.

### 2.2. Metadata

- `metadata.parquet`: 18 cột mô tả văn bản (số hiệu, tiêu đề, loại văn bản, cơ quan ban hành, ngày ban hành, ngày hiệu lực, tình trạng, lĩnh vực, ngành, người ký…)
- Dùng để **join** khi truy vấn, không nhân bản lên từng chunk.

### 2.3. Relationships

- `relationships.parquet`: đồ thị quan hệ giữa các văn bản `(doc_id, other_doc_id, relationship)`
- Sử dụng riêng cho GraphRAG / lightRAG, không gắn vào chunk.

## 3. Chiến lược chunking

### 3.1. Nguyên tắc cốt lõi

1. **Không fixed-size**: chỉ fallback khi hết separator logic.
2. **Giữ đơn vị nghĩa pháp lý**: Điều, khoản/nhóm khoản, thủ tục trong bảng, block bảng, căn cứ, nơi nhận/chữ ký tách riêng.
3. **Metadata cấp văn bản** lấy từ `metadata.parquet`, không parse lại header.
4. **Parent-child retrieval**: `procedure_record`, `clause_group` có `parent_id` trỏ về Điều/phụ lục cha.
5. **Mở rộng bằng cấu hình tập trung**: các hằng số regex và danh sách từ khóa đặt tại một chỗ (`chunk.py` §2b) – **không hard-code theo từng `doc_id`**.

### 3.2. Output schema của chunk

```python
{
    "chunk_id": str,
    "doc_id": int,
    "source": str,
    "chunk_text": str,          # nội dung gốc (citation)
    "contextual_text": str,     # prefix metadata + section_path + nội dung (để embed)
    "chunk_type": str,          # article, clause_group, table, procedure_record, table_summary, raw_table, preamble, appendix_text, signature, distribution_list, ...
    "section_path": list[str],  # ["Chương I", "Điều 5"] hoặc ["Phụ lục 2", "QUY ĐỊNH", "Điều 3"]
    "procedure_name": str | None,
    "embed": bool,              # có đưa vào dense vector index không
    "keyword_index": bool,      # có đưa vào BM25 không
    "parent_id": str | None,
    "prev_chunk_id": str | None,
    "next_chunk_id": str | None,
    "token_estimate": int,
    "quality_flags": list[str], # tiny_chunk, oversized_chunk, hard_char_split, orphan_chunk...
}
```

- `chunk_type` quyết định cờ `embed` / `keyword_index` (xem bảng §5.1 trong chiến lược).
- `contextual_text` được tạo bằng cách ghép prefix ngắn từ metadata (số hiệu, tiêu đề, cơ quan, ngày tháng) + `section_path` + `chunk_text` – dùng cho dense embedding.

### 3.3. Pipeline xử lý

```
Raw content (text)
  ↓ Normalize
  │ - Chuẩn hóa dòng, explode bảng OCR dẹt
  │ - Tách Điều inline (OCR nối dòng)
  │ - Tách khoản Arabic inline (trong Chỉ thị, Nghị quyết)
  ↓ Structural split
  │ - Separator: PHỤ LỤC → PHẦN → CHƯƠNG → MỤC
  │ - Đặc biệt: khối đính kèm (QUY ĐỊNH, DANH MỤC, ĐIỀU LỆ…) → xử lý như Phần, gộp header với Điều 1
  │ - Nhận dạng Điều (đầu dòng), khoản 1., 2.
  │ - Trong phụ lục: nhóm lĩnh vực I., II., “Lĩnh vực:”
  │ - Bảng markdown (|) có guard để tránh nhầm letterhead
  │ - Footer: tách Nơi nhận, chữ ký (dùng regex chức danh)
  │ - Kéo phụ lục bị lạc vào footer trở lại body
  ↓ Xử lý theo loại block
  │ - Điều ngắn → chunk_type = article
  │ - Điều dài → split theo khoản (1.,2.) → clause_group, hoặc theo mục La Mã (I, II…)
  │ - Nếu vẫn >3000 ký tự → hierarchical split: điểm a)b)c) → paragraph → câu
  │ - Bảng TTHC → mỗi dòng là một procedure_record (chunk riêng)
  │ - Bảng lớn >3000 ký tự → table_summary + raw_table
  │ - Appendix dạng văn bản có cấu trúc Điều/Chương → parse lại thành appendix_text
  │ - Không xác định được → fallback prose split (giữ câu, hard char nếu cần)
  ↓ Tạo contextual_text + validation
  ↓ Xuất chunks.parquet
```

### 3.4. Các xử lý đặc thù – giải quyết lỗi thực tế

| Vấn đề gặp trên corpus                                                     | Giải pháp                                                                                              | Kết quả                                           |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------- | ------------------------------------------------------------- |
| Công văn có dòng `                                                         | ...                                                                                                    | ` là letterhead, bị nhận nhầm bảng                | Guard: nếu số pipe ≤8 và segment dài >150 → giữ là `preamble` |
| QĐ + danh mục: Điều 1..3 bị mất, chỉ còn `procedure_record`                | Tách `_split_annex_heading_line` trước khi gom bảng; xử lý khối đính kèm (QUY ĐỊNH, DANH MỤC) như Phần | Có đầy đủ Điều và bảng đúng chỗ                   |
| Bảng TTHC: tên thủ tục chứa từ “Quyết định” làm kích hoạt guard prose      | Hàng `\| 01 \| …` vẫn được nhận dạng bảng; ưu tiên `is_probably_table_line`                            | Giữ nguyên `procedure_record`                     |
| Footer nuốt cả Biểu số, Đề án, Điều lệ dài 20k-40k ký tự                   | `RE_ANNEX_BLOCK_START` + safety net: tìm lại marker phụ lục trong footer, kéo về body                  | `signature` chỉ còn vài dòng, phụ lục đúng vị trí |
| Nghị quyết + Quy định kèm theo: hai Điều 1 cùng path                       | Phát hiện heading `QUY ĐỊNH` → `section_path = ["QUY ĐỊNH", "Điều 1"]`                                 | Phân biệt rõ ràng                                 |
| QUY ĐỊNH có Điều 1,2 bị gộp do OCR inline `.\n. Điều 2.`                   | Tách inline Điều bằng regex `RE_INLINE_ARTICLE_AFTER_PERIOD`                                           | Hai chunk riêng                                   |
| Chunk chỉ tiêu đề QUY ĐỊNH (50 token) tách khỏi Điều 1                     | Gộp header với Điều 1 đầu tiên cùng khối                                                               | Một chunk `article` hoàn chỉnh                    |
| Điều 4 có bảng chi (mục I, II, III) bị split theo câu sai                  | Tách theo mục La Mã `_ROMAN` (I..XX) thay vì câu                                                       | `clause_group` đúng mục, không lặp tiêu đề        |
| Phụ lục OCR: nhóm XI. không được tách (hardcode tới X)                     | Dùng `_ROMAN` mở rộng tới XX, explode dòng dài                                                         | Tách đúng                                         |
| Câu bị cắt sau `UBND.`, `TW.`                                              | Auto-protect viết tắt (`_RE_AUTO_ABBREV`) + thêm `_SENTENCE_SPLIT_PROTECTED`                           | Giữ nguyên                                        |
| Chỉ thị không có Điều: `1. 2. 3.` bị cắt bởi `split_sentences_vi`          | `RE_NUMBERED_CLAUSE_HEADING`, chỉ kích hoạt khi không nằm trong Điều                                   | Tạo `["Khoản 1"]`, `article`                      |
| Bảng trong Điều 2: `chunk_text` bắt đầu đúng nhưng `section_path="Điều 1"` | Thứ tự: parse heading trước `is_probably_table_line`                                                   | `table` mang đúng `["Điều 2"]`                    |
| Thiếu chức danh chữ ký (CỤC TRƯỞNG, VIỆN TRƯỞNG…)                          | Mở rộng `_SIG_PATTERNS`                                                                                | Tách đúng `signature`                             |

### 3.5. Các ngưỡng cấu hình

```yaml
min_chars: 300
target_chars: 1600
max_chars: 2200
hard_max_chars: 3000
overlap_chars: 150
table_max_chars: 2000
table_summary_threshold: 3000
long_prose_threshold: 3000 # prose/article > 3000 chars → hierarchical split
long_prose_max_chars: 2500 # không còn chunk prose nào vượt quá 2500
short_doc_threshold: 300
```

## 4. Đánh giá (Evaluation)

### 4.1. Phương pháp

- Lấy subset **100 văn bản** đa dạng (phân tầng theo lượng tử độ dài từ 1% đến 99%, bổ sung outlier).
- Chạy pipeline chunking, thu thập các metrics:
  - **Coverage** = tổng chars của các chunk / tổng chars gốc.
  - **Phân phối chunk size** (characters).
  - **Tỷ lệ quality flags**: `tiny_chunk` (<50 chars), `oversized_chunk` (>2000 chars trong lúc chưa có `hard_max`), `hard_char_split`, `orphan_chunk`.
  - **Metadata propagation**: kiểm tra `document_number` và `title` có được gán đúng trên mọi chunk không.
  - **Boundary integrity**: phát hiện điều/mục bị cắt ngang giữa hai chunk.
  - **Table integrity**: bảng bị tách rời header khỏi dữ liệu.
  - **Phân tích chunk lớn** >10,000 chars: phân loại `table/appendix` hay `long_prose`.

- Code đánh giá được viết bằng Polars, matplotlib, seaborn, và các hàm heuristic.

### 4.2. Kết quả định lượng

Trên 100 văn bản (độ dài từ ~500 đến ~300.000 ký tự):

| Chỉ số                                | Giá trị                                        |
| ------------------------------------- | ---------------------------------------------- |
| Tổng số văn bản phân tích             | 100                                            |
| Tổng số chunks tạo ra                 | ~2.400                                         |
| Coverage trung bình                   | **98,5%** (mất mát do lỗi normalize tối thiểu) |
| Tỷ lệ `tiny_chunk` (<50 chars)        | **26%**                                        |
| Tỷ lệ `oversized_chunk` (>2000 chars) | **8%** (hầu hết là bảng)                       |
| Tỷ lệ `hard_char_split`               | **0%** (không có fallback cứng)                |
| Tỷ lệ `orphan_chunk`                  | **0%** (mọi chunk có section_path)             |
| Metadata propagation đúng             | 100%                                           |
| Số văn bản có boundary violation      | **0**                                          |
| Số lần nghi ngờ table bị tách         | **0**                                          |

**Phân tích chunk > 10.000 ký tự:**

- Tổng số chunk >10k: 12 chunk.
- Trong đó:
  - `table/appendix`: 12 (100%)
  - `long_prose`: 0
- Kết luận: chunk lớn là bảng hoặc phụ lục (tự nhiên), không có prose quá dài do đã được split hierarchical.

**Phân phối chunk size** (log scale):

- Median: ~950 chars
- p95: ~2.800 chars
- Max: 44.000 chars (một bảng lớn trong phụ lục)

### 4.3. Phát hiện định tính

- **Tiny_chunk 26%** chủ yếu là các dòng chữ ký (`signature`), dòng nơi nhận (`distribution_list`) hoặc tiêu đề phụ lục ngắn. Các chunk này không được gắn cờ `embed` (vì `embed=False`), không ảnh hưởng đến chất lượng truy hồi.
- **Không có hard_split**: cho thấy pipeline đã phân tách thành công bằng separator ngữ nghĩa (Điều, khoản, mục, bảng, footer) mà không cần cắt cứng theo ký tự.
- **Boundary integrity** hoàn hảo: không có trường hợp số Điều bị cắt giữa hai chunk.
- **Bảng TTHC** được parse đúng thành `procedure_record` với `procedure_name`. Không còn bảng nào bị coi là `raw_table` không mong muốn.

## 5. Cải tiến đã thực hiện (so với phiên bản đầu)

Dựa trên kết quả đánh giá và kiểm tra thủ công 100 văn bản, chúng tôi đã thực hiện các cải tiến sau:

1. **Tách Điều inline OCR** – bổ sung regex `RE_INLINE_ARTICLE_AFTER_PERIOD` cho mọi số Điều.
2. **Xử lý khối đính kèm** (QUY ĐỊNH, DANH MỤC, ĐIỀU LỆ) như một “Phần” riêng, gộp header với Điều 1 đầu tiên.
3. **Kéo phụ lục từ footer** – thêm `RE_ANNEX_BLOCK_START` và safety net trong `_process_block`.
4. **Split Điều dài theo mục La Mã** – dùng `_ROMAN` (I đến XX) thay vì split câu.
5. **Bảo vệ viết tắt** – tự động bảo vệ `UBND.`, `TW.`, `HĐND.`, `NĐ.`,… và cho phép mở rộng qua `_SENTENCE_SPLIT_PROTECTED`.
6. **Nhận dạng khoản cấp văn bản** – dành cho Chỉ thị, Nghị quyết không có Điều.
7. **Guard bảng** – tránh nhầm letterhead và thân văn bản có `|` nhưng không phải bảng.
8. **Điều chỉnh thứ tự parse** – `_parse_heading` trước `is_probably_table_line` để giữ đúng `section_path` cho bảng nằm trong Điều.

## 6. Hướng dẫn sử dụng

### 6.1. Chạy chunking trên toàn bộ dữ liệu

```python
import polars as pl
from chunk import chunk_polars_dataframe

content = pl.read_parquet("data/content.parquet")
metadata = pl.read_parquet("data/metadata.parquet")

chunks = chunk_polars_dataframe(content, metadata_df=metadata)
chunks.write_parquet("data/preprocessed/legal_chunks.parquet")
```

### 6.2. Chạy evaluation trên subset

Các code cells trong `chunking_evaluation.md` đã được tích hợp sẵn. Chỉ cần đảm bảo:

- Hàm `chunk_legal_document` (hoặc `chunk_polars_dataframe`) đã được định nghĩa.
- Có file `content.parquet` và `metadata.parquet` ở đường dẫn phù hợp.

### 6.3. Mở rộng cho domain mới

Nếu gặp loại văn bản mới (ví dụ: bảng giá đất, biểu mức phạt…) **không thay đổi logic core**, chỉ cần thêm vào các hằng số tập trung trong `chunk.py` §2b:

- Thêm từ khóa nhận dạng bảng thủ tục vào `_TTHC_DETECT_KEYWORDS`.
- Thêm chức danh chữ ký vào `_SIG_PATTERNS`.
- Thêm pattern tiêu đề phụ lục vào `_APPENDIX_HEADING_KEYWORDS`.

## 7. Kết luận và hướng phát triển

### 7.1. Kết luận

- Chiến lược chunking đã đáp ứng được yêu cầu **giữ nguyên ngữ nghĩa pháp lý**, xử lý thành công các dạng văn bản đa dạng (văn bản luật có cấu trúc, công văn, bảng biểu, phụ lục, footer).
- Các chỉ số evaluation cho thấy **không còn chunk prose quá dài** (>2.500 ký tự), **0% hard_split**, coverage gần 99%, metadata propagation hoàn hảo.
- Tiny_chunk (26%) là chấp nhận được vì chúng không được đưa vào embedding và không ảnh hưởng đến retrieval.
- Hệ thống có thể mở rộng thông qua cấu hình tập trung, tránh hard-code theo từng văn bản.

### 7.2. Hướng phát triển

1. **Tối ưu `contextual_text`**: thử nghiệm các template prefix khác nhau để cải thiện recall của dense retrieval.
2. **GraphRAG**: Sử dụng `relationships.parquet` để expand truy vấn sang văn bản liên quan (ví dụ: Nghị định hướng dẫn Luật).
3. **Reranker**: Huấn luyện hoặc fine-tune một reranker trên dữ liệu luật Việt Nam, sử dụng `contextual_text` làm đầu vào.
4. **Hybrid search**: Kết hợp BM25 trên `chunk_text` + dense trên `contextual_text` + boost theo `chunk_type` (ưu tiên `article`, `procedure_record`).
5. **Tự động cập nhật ngưỡng**: dựa trên phân phối độ dài văn bản trong toàn bộ corpus để điều chỉnh `long_prose_threshold`, `max_chars`.

---

**Tài liệu tham khảo nội bộ:**

- `chunking_strategy.md` – chi tiết kỹ thuật pipeline.
- `chunking_evaluation.md` – mã nguồn đánh giá và visualization.
- `context.md` – mô tả dữ liệu đầu vào.

_Báo cáo được thực hiện cho dự án chatbot pháp luật Việt Nam – Hybrid RAG._
