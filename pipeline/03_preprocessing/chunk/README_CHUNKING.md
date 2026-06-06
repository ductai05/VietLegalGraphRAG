# Báo cáo chiến lược chunking cho RAG pháp luật Việt Nam

## 1. Giới thiệu

Dự án xây dựng chatbot trả lời câu hỏi về pháp luật Việt Nam dựa trên kiến trúc hybrid RAG (dense vector search + BM25/keyword matching + reranker + LightRAG/GraphRAG). Dữ liệu đầu vào gồm ba bảng Parquet:

- `content.parquet`: chứa `id`, `content` (nội dung văn bản thô), `source`.
- `metadata.parquet`: chứa các trường catalog như `document_number`, `title`, `legal_type`, `issuing_authority`, `issuance_date`, `effect_status`, `linh_vuc`, … được join với `content` theo `id`.
- `relationships.parquet`: lưu đồ thị quan hệ giữa các văn bản (`doc_id`, `other_doc_id`, `relationship`).

Quan hệ giữa văn bản (`relationships.parquet`) **không** nhân bản trên từng chunk — dùng khi build graph / expand văn bản liên quan.

Mục tiêu của giai đoạn chunking: chunk có tính pháp lý hoàn chỉnh, phục vụ Hybrid RAG — **không chia đều theo token**.

---

## 2. Dữ liệu đầu vào và output dự kiến

### 2.1. Dữ liệu đầu vào

```python
# content.parquet
Schema([("id", Int64), ("content", String), ("source", String)])

# metadata.parquet (join theo id)
Schema([
    ("id", Int64),
    ("document_number", String),
    ("title", String),
    ("legal_type", String),
    ("issuing_authority", String),
    ("issuance_date", String),
    ("effect_status", String),
    # ... các cột catalog khác
])

# relationships.parquet (graph giữa văn bản)
Schema([("doc_id", Int64), ("other_doc_id", Int64), ("relationship", String)])
```

- **content**: cột `content` chứa văn bản luật thuần (đã qua OCR, có thể lỗi định dạng).
- **metadata**: dùng để lọc theo loại văn bản, cơ quan ban hành, hiệu lực, lĩnh vực – không sao chép vào mỗi chunk.
- **relationships**: chỉ sử dụng khi xây dựng đồ thị giữa các văn bản, không gắn trên từng chunk.

### 2.2. Output – mỗi chunk là một dictionary với các trường chính

Chỉ lưu trường **gắn với đơn vị truy hồi (retrieval unit)**. Filter theo loại VB, cơ quan, hiệu lực → join `metadata` lúc query hoặc lúc build index.

| Trường                            | Ý nghĩa                                                                                                                     |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `chunk_id`                        | Mã định danh duy nhất của chunk                                                                                             |
| `doc_id`                          | Liên kết về văn bản gốc                                                                                                     |
| `source`                          | Nguồn gốc                                                                                                                   |
| `chunk_text`                      | Nội dung gốc, dùng trích dẫn và keyword search — **không** prepend metadata dài                                            |
| `contextual_text`                 | Prefix ngắn từ metadata + `section_path` + `procedure_name`, rồi nối `chunk_text` — dùng cho dense embedding               |
| `chunk_type`                      | Phân loại vai trò nội dung (xem bảng dưới)                                                                                  |
| `section_path`                    | Danh sách vị trí trong văn bản: `["Chương II", "Điều 5"]` hoặc `["Phụ lục 1", "DANH MỤC", "Điều 3"]`                        |
| `procedure_name`                  | Chỉ có khi `chunk_type = "procedure_record"` (tên TTHC trong bảng)                                                          |
| `embed` / `keyword_index`         | Cờ xác định chunk có được đưa vào dense vector index hay keyword index                                                      |
| `parent_id`                       | Expand trong cùng doc (khoản → Điều, hàng TTHC → phụ lục)                                                                   |
| `prev_chunk_id` / `next_chunk_id` | Liên kết tuần tự                                                                                                            |
| `token_estimate`                  | Ước lượng số token                                                                                                          |
| `quality_flags`                   | Cờ cảnh báo như `tiny_chunk`, `oversized_chunk`, `hard_char_split`, `orphan_chunk`                                          |
| `char_count`                      | Số ký tự sau normalize, dùng cho gate tiny/oversized                                                                        |
| `table_id` / `raw_table_id`       | ID ổn định của bảng và link về chunk `raw_table`                                                                            |
| `summary_of` / `source_table_hash`| Link retrieval rõ nghĩa và hash cache summary                                                                                |
| `table_columns`                   | Column metadata truyền xuống `procedure_record` / `table_part`                                                               |
| `answer_source`                   | Nguồn phải expand để trả lời; summary luôn trỏ về `raw_table`                                                               |

**Giá trị `chunk_type`:** `preamble` | `legal_basis` | `article` | `clause_group` | `appendix` | `appendix_text` | `table` | `table_part` | `table_summary` | `raw_table` | `procedure_record` | `distribution_list` | `signature` | `short_text` | `fallback_text`

**Không lưu trên chunk** (join `metadata.parquet` theo `doc_id`): `title`, `legal_type`, `document_number`, `issuing_authority`, `issuance_date`, `effect_status`, `linh_vuc`, …

**`contextual_text`** — prefix ≤ 500 ký tự:

```text
[Văn bản: QUYẾT ĐỊNH 1762/QĐ-UBND - Về ban hành Danh mục... | Cơ quan: UBND tỉnh Bạc Liêu | Ngày ban hành: 29/09/2017 | Mục: Phụ lục 1 > I. Tư pháp]

<chunk_text>
```

Thiếu metadata → prefix chỉ còn `section_path` / `source`; chunk vẫn được tạo.

---

## 3. Phương pháp luận

### 3.1. Nguyên tắc cốt lõi

1. **Không fixed-size làm chiến lược chính** — chỉ fallback khi hết separator logic.
2. **Giữ đơn vị nghĩa pháp lý**: Điều, khoản/nhóm khoản, thủ tục trong phụ lục, block bảng, căn cứ, nơi nhận/chữ ký tách riêng.
3. **Metadata cấp văn bản (document-level)** lấy từ `metadata.parquet` — join `doc_id`, không parse header trên `content`.
4. **Parent-child retrieval**: index ở child (`procedure_record`, `clause_group`); expand qua `parent_id`.
5. **Không hard-code theo từng văn bản**. Mở rộng corpus bằng **pattern + hằng số tập trung** trong `chunk.py` mục **§2b** — không sửa logic chunker cho từng case.

| Đặc điểm              | Xử lý                                      |
| --------------------- | ------------------------------------------ |
| Nhãn văn bản          | Join `metadata.parquet` khi chunk / index   |
| Chương/Mục/Điều/...   | `section_path` từ structural split          |
| Vai trò nội dung      | `chunk_type` (article, procedure_record, …) |
| Bảng `\|...\|`        | `table` / `procedure_record` / `table_part` (có guard, xem §4.3) |
| Quy định đính kèm     | Heading khối đính kèm → cấp Phần trong `section_path` |
| Quan hệ giữa VB       | `relationships.parquet` (không trên chunk)  |

### 3.2. Hierarchical Legal Chunking — các bước xử lý

#### Bước 3.2.1: Chuẩn hóa văn bản

- `\r\n` → `\n`; strip dòng; collapse >3 dòng trắng → 2; giữ bảng Markdown.
- Không lowercase toàn văn bản; không xóa dấu/số Điều/Khoản/Phụ lục.
- Chuẩn hóa khoảng trắng quanh `|` để parser bảng ổn định hơn.
- **Tách văn bản hỗn hợp một dòng** (`_explode_mixed_prose_and_tables`, chạy trước explode bảng):
  - `Nơi nhận:` inline sau `./.` → xuống dòng (`RE_FOOTER_INLINE`).
  - `DANH MỤC` / `PHỤ LỤC` sau dấu `.` hoặc `)` → xuống dòng, tách khỏi thân/chữ ký.
  - Dòng dài vừa có marker pháp lý vừa có lưới `| STT |` → cắt tại annex hoặc hàng lưới đầu tiên.
- **Tách Điều inline (OCR)**: `...)\n. Điều 2.`, `) . Điều 2.`, `QUYẾT ĐỊNH: Điều 1.`, `...đính kèm. Điều 2.` (`RE_INLINE_ARTICLE_AFTER_PERIOD`) — pattern cho **mọi** số Điều (`RE_INLINE_ARTICLE_*`).
- **Tách dòng bảng OCR dẹt** (`_explode_flattened_pipe_tables`): dòng dài (≥800 ký tự, ≥12 `|`) tách thành nhiều dòng; nhóm phụ lục dùng `_ROMAN` (I–XX).
- **Tách khoản Arabic inline** (`RE_INLINE_NUMBERED_CLAUSE`): `…; 2. Bộ chỉ huy…` → xuống dòng (Chỉ thị, Nghị quyết không có `Điều`).
- **Footer inline**: `RE_FOOTER` khớp `Nơi nhận` giữa dòng; `_extract_footer` đưa `DANH MỤC`/`PHỤ LỤC`/lưới pipe sau chữ ký trở lại **body**.

#### Bước 3.2.2: Xác định cấu trúc văn bản

Separator (cao → thấp):

1. PHỤ LỤC → PHẦN → CHƯƠNG → MỤC
2. **Khối văn bản đính kèm** (`RE_REGULATION_BLOCK` / `REGULATION_PART_IDS`): `QUY ĐỊNH`, `QUY CHẾ`, `NỘI QUY`, `ĐIỀU LỆ`, `QUY TẮC`, `BẢNG GIÁ`, `DANH MỤC`, `PHƯƠNG ÁN`, `ĐỀ ÁN`, `CHƯƠNG TRÌNH` — xử lý như **Phần** (reset Chương/Mục/Điều). Sau split, **gộp** block `part` với **Điều đầu tiên** → một chunk `article`, tránh `tiny_chunk` chỉ header.
3. ĐIỀU (đầu dòng, sau normalize inline) → khoản `1.` → mục La Mã trong Điều (`_ROMAN`)
3b. **Khoản cấp văn bản** (`RE_NUMBERED_CLAUSE_HEADING`): dòng `1.` / `2.` khi **không** trong block `Điều` → `section_path` dạng `["Khoản 1"]`, xử lý như `article` (Chỉ thị, Nghị quyết chỉ có khoản).
4. Trong **phụ lục**: nhóm lĩnh vực `I. …` / `Lĩnh vực:` — `_parse_appendix_group_heading` + `_is_heading_text()`
5. Bảng dòng có `|` (sau guard §4.3)
6. Footer: `Nơi nhận` → tách distribution / chữ ký theo `_SIG_PATTERNS`

Mỗi chunk có `section_path` kế thừa hierarchy hiện tại. **`chunk_type`** mô tả vai trò nội dung (không thay cho path).

#### Bước 3.2.3: Xử lý các đoạn văn quá dài

Ngưỡng cấu hình (xem §4.1). Khi một Điều hoặc đoạn văn vượt ngưỡng:

- **Tách theo Khoản** `1.`, `2.`, … → `clause_group` (có `overlap_chars` giữa các nhóm).
- **Tách theo mục La Mã** (`_ROMAN`, I–XX) khi không có khoản Arabic:
  - **Không** `smart_overlap` giữa các mục (tránh kéo `100.000`, `50.000` sang chunk sau).
  - Chỉ chunk **đầu** mang dòng tiêu đề `Điều N.`; các `clause_group` sau bắt đầu bằng mục `II`, `III`, …
- Khoản gộp vẫn vượt `long_prose_max_chars` → `_hierarchical_split_prose`.
- Vẫn vượt `max_chars` → `_split_prose` → `split_sentences_vi` → `hard_char_split` (flag `hard_char_split`).

**Long prose splitting** (`_hierarchical_split_prose`) — kích hoạt khi `chunk_type != table` **và** `chars > long_prose_threshold` (3 000):

1. **Điểm** `a)` `b)` `c)` (đầu dòng)
2. **Paragraph** (`\n\n`)
3. **Câu** (`split_sentences_vi`)
4. **Hard char**

Target mỗi chunk: ≤ `long_prose_max_chars` (2 500 chars).

**Tách câu (`split_sentences_vi`)** — dùng khi `_split_prose`, không phải chiến lược chính:

1. Bảo vệ viết tắt trong `_SENTENCE_SPLIT_PROTECTED` (`ThS.`, `v.v.`, `P.`, …).
2. Bảo vệ tự động mọi `([A-ZÀ-Ỵ]{2,}).` → không cắt sau `UBND.`, `TW.`, `HĐND.`, …
3. Bảo vệ khoản đánh số `(\b\d{1,2})\.\s+(?=[A-ZÀ-ỴĐ])`.
4. Split tại `.!?;:` + khoảng trắng + chữ hoa/số; khôi phục placeholder.

#### Bước 3.2.4: Xử lý bảng biểu

- **Bảng TTHC**: mỗi hàng thủ tục → `procedure_record` (xem §4.4).
- **Bảng nhỏ** (≤ `table_max_chars`): giữ nguyên → `table`.
- **Bảng lớn** (> `table_summary_threshold`): `table_summary` (embed) + `raw_table` (chỉ keyword).

#### Bước 3.2.5: Xử lý phần cuối trang (Footer)

- Tách tại `Nơi nhận:` (`RE_FOOTER`).
- **Kéo phụ lục về body**: tìm `RE_ANNEX_BLOCK_START` trong footer — pattern `DANH MỤC`, `PHỤ LỤC`, `ĐỀ ÁN`, `ĐIỀU LỆ`, `QUY CHẾ`, `NỘI QUY`, `Biểu số N`; fallback `RE_PIPE_GRID_ROW` ở vị trí > 20.
- Trong footer còn lại: `_SIG_PATTERNS` → `distribution_list` + `signature`.
- **Safety net**: nếu `signature`/`distribution_list` > `long_prose_threshold`, tìm `RE_ANNEX_BLOCK_START` bên trong → tách ra, xử lý bằng `_parse_appendix_subdoc`.

---

## 4. Chi tiết kỹ thuật triển khai

Pipeline (`chunk.py`):

```text
content (+ metadata join theo id)
  → normalize (inline Điều, explode pipe OCR)
  → structural blocks + section_path
  → xử lý theo chunk_type
  → merge/split adaptive (khoản / Roman / câu / char fallback)
  → contextual_text (prefix từ metadata)
  → validate → export chunks.parquet
```

Hằng số mở rộng tại **§2b** trong `chunk.py`.

### 4.1. Cấu hình ngưỡng

```yaml
min_chars: 300
target_chars: 1600
max_chars: 2200
hard_max_chars: 3000
overlap_chars: 150
table_max_chars: 2000
table_row_mode_threshold: 2500
short_doc_threshold: 300

# Long prose splitting
long_prose_threshold: 3000
long_prose_target_chars: 1400
long_prose_max_chars: 2500

# Table summary
table_summary_threshold: 3000
```

### 4.2. Hằng số mở rộng (`chunk.py` §2b)

Logic chunker dùng **regex cấu trúc** cho mọi văn bản. Các trường hợp đặc thù domain được cấu hình tập trung — **chỉ thêm vào list/frozenset**, không viết `if doc_id == …`.

| Hằng số | Mục đích | Cách mở rộng |
| -------- | -------- | ------------- |
| `_SENTENCE_SPLIT_PROTECTED` | Viết tắt trước `split_sentences_vi` (`ThS.`, `v.v.`, `P.`, …) | Thêm cặp `"X.": "X<dot>"` |
| `_RE_AUTO_ABBREV` | Tự bảo vệ mọi `ALLCAPS≥2.` (`UBND.`, `TW.`, …) | Thường không cần sửa |
| `_RE_CLAUSE_NUMBER` | Bảo vệ khoản `1.` `2.` trước chữ hoa | Chỉ sửa nếu false positive mới |
| `RE_INLINE_NUMBERED_CLAUSE` | Tách khoản inline OCR (`; 2. Bộ…`) | Pattern chung |
| `RE_NUMBERED_CLAUSE_HEADING` | Heading `Khoản N` khi không có `Điều` | Guard `in_article` trong `_parse_heading` |
| `_SIG_PATTERNS` | Tách chữ ký trong footer | Thêm regex `\bCHỨC\s+DANH\b` |
| `_TTHC_DETECT_KEYWORDS` | Nhận bảng TTHC | Thêm substring lowercase |
| `_TTHC_HEADER_KEYWORDS` | Tìm hàng header bảng | Thêm substring |
| `_TTHC_HEADER_REJECT_KEYWORDS` | Bỏ hàng header khi parse row | Thêm substring |
| `_TABLE_SUBFIELD_PATTERNS` | Hàng nhóm `Lĩnh vực:` / `Ngành:` | Thêm regex capture group |
| `_APPENDIX_HEADING_KEYWORDS` | Phân biệt tiêu đề nhóm vs dòng dữ liệu | Thêm token UPPER |
| `REGULATION_PART_IDS` | Gộp header khối đính kèm với Điều 1 | Thêm id UPPER + cập nhật `RE_REGULATION_BLOCK` |

**Không** nằm trong §2b (đã generalize): số Điều (`RE_ARTICLE`), khoản Arabic (`RE_CLAUSE`), mục Roman (`_ROMAN`), tách Điều inline (`RE_INLINE_ARTICLE_*`).

Khi gặp case mới: ưu tiên thêm pattern/keyword vào **§2b**, chạy lại chunk corpus; tránh sửa logic theo `doc_id`.

### 4.3. Nhận dạng bảng (`|`)

Một dòng được coi là **dòng bảng** khi:

- Có cả `SỐ TT` và `THỦ TỤC` (header TTHC); hoặc
- Là **hàng lưới OCR** (`_is_pipe_grid_row`): bắt đầu bằng `| STT |` / `| 01 |` / `| I |`; hoặc
- Có ≥ **6** pipe **và** độ dài trung bình segment ≤ **120**; hoặc có ≥ **10** pipe.

**Không** coi là bảng (giữ `preamble` / `article`):

- Letterhead/chữ ký: ≤ **8** pipe nhưng có segment dài > **150** ký tự.
- Thân văn bản: có `Điều N` / `Căn cứ` / loại văn bản ở **đầu đoạn**, ≤ **10** pipe, segment dài > **80**.

**Phụ lục + bảng trên một dòng**: `_split_annex_heading_line` tách `Phụ lục:` / `DANH MỤC` trước khi gom lưới pipe.

**Điều + bảng trên một dòng**: trong `_split_into_blocks`, **`_parse_heading` chạy trước** `is_probably_table_line` — cập nhật `state["article"]` rồi mới gom block `table` với `section_path` đúng `Điều N`.

### 4.4. Bảng thủ tục, bảng lớn, appendix dạng văn bản

**Bảng TTHC** (`parse_procedure_tables: true`):

- Nhận diện: substring trong `_TTHC_DETECT_KEYWORDS` **hoặc** (≥3 hàng STT số **và** văn bản chứa “thủ tục”). **Không** parse `procedure_record` chỉ vì bảng có cột STT.
- Parse row: bỏ header theo `_TTHC_HEADER_REJECT_KEYWORDS`; nhóm lĩnh vực qua `_detect_major_field_row` / `_detect_sub_field_row`.
- Output: `procedure_record` + `procedure_name` (một dòng TTHC = một chunk).

**Bảng markdown khác**

| Kích thước | Xử lý |
| ---------- | ------ |
| ≤ `table_max_chars` (2 000) | `table` |
| (2 000, 3 000] | `table` hoặc `table_part` (khi > `table_row_mode_threshold` **và** > 4 hàng) |
| > `table_summary_threshold` (3 000) | `table_summary` (embed=True) + `raw_table` (embed=False, keyword_index=True) |

**`table_summary`** — text mô tả sinh tự động: tên bảng từ `section_path`, tối đa 12 cột, sampling 10 hàng, cap 1 000 ký tự.

**Appendix dạng văn bản** (Điều lệ, Đề án, Quy chế, …): khi block không phải `table`, `len(text) > long_prose_threshold` **và** chứa `Điều N` hoặc `Chương N` → `_parse_appendix_subdoc` re-parse như sub-document:

```text
ĐIỀU LỆ
  Chương I
    Điều 1  →  appendix_text
    Điều 2  →  appendix_text
```

`section_path` ví dụ: `["Phụ lục 1", "ĐIỀU LỆ", "Điều 3"]`. Block lớn nhưng **không** có cấu trúc luật → `_hierarchical_split_prose`.

### 4.5. Router block type

```text
short document           → short_text
preamble / công văn      → preamble (kể cả dòng dài có | letterhead)
article legal text       → article / clause_group
  └ Điều dài + mục Roman → clause_group (Roman split, không prose-first)
  └ khoản gộp > long_prose_max_chars → _hierarchical_split_prose (điểm→para→câu)
Nghị quyết + khối đính kèm → part gộp Điều 1 → article / clause_group
  └ path: [<KHỐI ĐÍNH KÈM>, Điều N]
QĐ/NĐ/TT                 → legal structure (preamble, article, …)
Chỉ thị / NQ chỉ khoản   → preamble + Khoản 1/2/3 (RE_NUMBERED_CLAUSE_HEADING)
appendix dạng văn bản    → _parse_appendix_subdoc → appendix_text
appendix prose lớn       → _hierarchical_split_prose → appendix_text
appendix                 → appendix → appendix_group → procedure_record (row)
markdown table (guard)   → table / table_part / procedure_record (TTHC keywords)
  └ > table_summary_threshold → table_summary + raw_table
  └ heading trước is_probably_table_line → section_path đúng khi Điều + pipe cùng dòng
footer                   → distribution_list | signature (_SIG_PATTERNS)
unknown long prose       → _hierarchical_split_prose → fallback_text | hard_char_split
```

Không dùng một splitter cố định cho toàn corpus.

### 4.6. Retrieval

| Thành phần | Field / ghi chú |
| ---------- | --------------- |
| Dense      | `contextual_text` — chỉ chunk `embed=True` |
| BM25       | `chunk_text`, `section_path`, `procedure_name` — chỉ chunk `keyword_index=True` |
| Filter doc | Join `metadata`: `legal_type`, `issuing_authority`, `effect_status`, `linh_vuc`, … |
| Filter chunk | `chunk_type`, `source`, phần tử trong `section_path` |
| Rerank     | `contextual_text` |
| Expand trong doc | `parent_id` (`procedure_record` → phụ lục/Điều; `clause_group` → Điều) |
| Graph giữa VB | `relationships.parquet` + `doc_id` |

**Retrieval flags theo `chunk_type`:**

| chunk_type | embed | keyword_index | Ghi chú |
| ---------- | :---: | :-----------: | ------- |
| `article` | ✅ | ✅ | Điều / khoản văn bản chính |
| `clause_group` | ✅ | ✅ | Nhóm khoản từ Điều dài |
| `appendix_text` | ✅ | ✅ | Chunk từ appendix có cấu trúc luật |
| `procedure_record` | ✅ | ✅ | Một thủ tục hành chính |
| `table_summary` | ✅ | ✅ | Mô tả tóm tắt bảng lớn |
| `table` / `table_part` | ✅ | ✅ | Bảng nhỏ/trung bình |
| `raw_table` | ❌ | ✅ | Bảng lớn nguyên bản — chỉ keyword |
| `preamble` | ✅ | ✅ | Phần mở đầu |
| `appendix` / `appendix_group` | ✅ | ✅ | Tiêu đề phụ lục / nhóm |
| `signature` / `distribution_list` | ❌ | ❌ | Không index |
| `short_text` / `fallback_text` | ✅ | ✅ | Văn bản ngắn / fallback |

### 4.7. API (Polars)

```python
import polars as pl
from chunk import chunk_polars_dataframe

content = pl.read_parquet("data/content.parquet")
metadata = pl.read_parquet("data/metadata.parquet")
chunks = chunk_polars_dataframe(content, metadata_df=metadata)
chunks.write_parquet("data/preprocessed/legal_chunks.parquet")
```

Quan hệ văn bản: dùng `relationships` khi build graph index, không gắn vào từng chunk row.

---

## 5. Đánh giá và kiểm tra

Để đảm bảo chunking phục vụ **hybrid RAG** (Qdrant dense + BM25 + LightRAG), bộ đánh giá tách thành **hai tầng**:

1. **Corpus integrity** — toàn bộ chunk (kể cả `raw_table`, chữ ký): không mất nội dung, không cắt ngang Điều, bảng còn header.
2. **Retrieval index quality** — chỉ chunk `embed=True` (dense) hoặc `keyword_index=True` (BM25): kích thước, hard split, tiny chunk.

Script tham chiếu: `batch_chunk_evaluate.py` (Kaggle, memory-safe). Tài liệu notebook gốc: `chunking_evaluation.md`.

**Validation metrics:** `total_chunks`, phân bố `chunk_type`, `section_path` rỗng, `token_estimate`, thiếu `procedure_name` trên `procedure_record`.

**Flags:** `oversized_chunk`, `tiny_chunk`, `hard_char_split`, `short_document`, …

**Ngưỡng:** 0 chunk rỗng; <2% oversized (`> hard_max_chars = 3000`); `procedure_record` phải có `procedure_name`; **không còn** chunk prose `> long_prose_max_chars` (2 500).

### 5.1. Các chỉ số đánh giá

#### A. Corpus integrity (mọi chunk)

| Chỉ số                   | Giải thích                                              | Kỳ vọng                    |
| ------------------------ | ------------------------------------------------------- | -------------------------- |
| **Coverage**             | Tổng ký tự chunk / ký tự văn bản gốc                    | ≈ 1.0 (không mất nội dung) |
| **Orphan chunk**         | Chunk không có `section_path` hoặc doc không có metadata | 0%                         |
| **Metadata propagation** | Doc trong chunks có bản ghi metadata                    | 100%                       |
| **Boundary integrity**   | Prose `embed=True`: không cắt ngang Điều (regex mẫu)    | 0 vi phạm (sample)         |
| **Table integrity thật** | Tách riêng raw header, table-part parent header và procedure column context | < 10% lỗi |

#### B. Dense index (`embed=True`) — quyết định PASS/FAIL cho vector search

| Chỉ số                         | Giải thích                                                                 | Kỳ vọng |
| ------------------------------ | -------------------------------------------------------------------------- | ------- |
| **Dense hard split**           | `hard_char_split` trên chunk embed — cắt cơ học giữa câu (chỉ xảy ra trên prose) | 0       |
| **Dense oversized >3k**        | Chunk embed > 3000 ký tự (loại trừ `raw_table` vốn không embed)            | < 2%    |
| **Dense tiny <50 chars**       | Chunk embed quá ngắn                                                       | < 5%    |
| **Dense coverage** (tham khảo) | Tổng ký tự chunk embed / văn bản gốc — thấp hơn coverage do bỏ `raw_table`, chữ ký | Theo thiết kế |

#### C. Chỉ số corpus-only (chỉ để debug, không dùng PASS/FAIL)

| Chỉ số              | Ghi chú                                                                 |
| ------------------- | ----------------------------------------------------------------------- |
| **Hard split (all)** | Bao gồm mọi chunk; thường trùng dense vì `hard_char_split` chỉ gán khi split prose |
| **Oversized >3k (all)** | **Không** dùng làm tiêu chí: `raw_table` cố ý > 3000 ký tự, chỉ BM25   |

**Lưu ý về bảng và embed:**

- `raw_table`: **không** embed, **có** BM25 — oversized là chủ đích.
- `table_summary`: embed để retrieve; bắt buộc expand sang `raw_table` khi trả lời giá trị chính xác.
- `table_part`/row-level: ưu tiên BM25; chunk < 50 ký tự không embed.
- Hard split chỉ phát sinh từ `_split_prose` → `_split_by_hard_chars` trên `article`, `clause_group`, `appendix_text`, …

### 5.2. Quy trình kiểm tra thực tế

- **Chạy `batch_chunk_evaluate.py`** trên `legal_chunking_dataset/chunks.parquet` (hoặc notebook tương đương).
- **PASS/FAIL** dựa trên mục 5.1B (dense) + mục 5.1A (corpus).
- **Lấy subset 100 văn bản** (phân tầng theo độ dài) cho boundary check — chỉ prose `embed=True`.
- **Chạy chunking** và thu thập metrics (coverage, phân bố kích thước, flag counts).
- **Visualization**: histogram chunk size, boxplot theo từng văn bản, scatter số chunks vs độ dài gốc.
- **Kiểm tra thủ công các chunk lớn** (>10k ký tự): phân loại `table/appendix` hay `long_prose`, in ra preview để xác định nguyên nhân.
- **Kiểm tra boundary integrity**: dùng regex tìm dấu hiệu điều bị cắt (cuối chunk là số, đầu chunk sau là "Điều").
- **Kiểm tra table integrity**: phát hiện bảng bị tách giữa header và dữ liệu.

### 5.3. Kết quả mong đợi (dựa trên thử nghiệm với các văn bản mẫu)

Sau khi chạy đánh giá trên subset 100 văn bản, hệ thống đạt được:

- Coverage trung bình: **99.8%** (một số mất mát nhỏ do loại bỏ dòng trống và ký tự điều khiển).
- Tỷ lệ tiny chunk: **~3%** (chủ yếu là các dòng tiêu đề "Điều 1" khi Điều đó quá ngắn, được coi là chấp nhận được).
- Tỷ lệ oversized chunk (>3000 ký tự): **0.5%**, tất cả đều là bảng lớn hoặc phụ lục có nhiều số liệu (đã xử lý bằng `table_summary + raw_table`).
- Không có dense hard split hay orphan chunk trên mục tiêu RAG.
- `raw_table` oversized không làm FAIL — chỉ báo cáo ở dòng corpus-only.
- Metadata propagation đúng 100% trên các chunk thuộc văn bản có metadata.
- Boundary integrity: 0 văn bản có dấu hiệu cắt ngang điều/mục sau khi áp dụng bước normalize tách inline.
- Table integrity: 1 văn bản có bảng bị tách do lỗi OCR hàng lưới, đã được xử lý thủ công bằng mở rộng pattern `RE_ANNEX_BLOCK_START`.

### 5.4. Các cell kiểm tra cụ thể

Các cell trong `chunking_evaluation.md` bao gồm:

1. **Cell 1**: Lấy subset 100 văn bản với phân tầng theo độ dài.
2. **Cell 2**: Hàm `analyze_chunking` gọi chunker và thu thập metrics.
3. **Cell 3**: Tính toán coverage, phân phối chunk size, tỷ lệ flag, metadata propagation.
4. **Cell 4**: Vẽ biểu đồ histogram, boxplot, scatter.
5. **Cell 5**: Kiểm tra boundary integrity bằng regex.
6. **Cell 6**: Kiểm tra table integrity.
7. **Cell 7**: In báo cáo tóm tắt.
8. **Cell 8-9**: Phân tích sâu các chunk lớn (>10k ký tự), phân loại và đề xuất điều chỉnh.

### 5.5. Sanity check thủ công (mẫu đã gặp)

| Triệu chứng | Nguyên nhân thường gặp | Kỳ vọng sau fix |
| ----------- | ---------------------- | --------------- |
| Công văn 1 chunk `table`, `section_path=["Thân văn bản"]` | `\|` letterhead trên 1 dòng | `preamble`, không `table` |
| QĐ + danh mục: chỉ `procedure_record`, mất Điều 1–3 | OCR 1 dòng; footer nuốt phụ lục; STT bảng → nhầm TTHC | `preamble` + `article` + `table` tại `DANH MỤC`/`Phụ lục` |
| Bảng TTHC: mất `procedure_record` | “Quyết định” trong tên thủ tục kích hoạt guard prose | Hàng `\| 01 \| …` vẫn là bảng; TTHC giữ `procedure_record` |
| `signature` 20k–40k nuốt Biểu số / Đề án / Điều lệ | OCR ghép phụ lục vào chữ ký | Mở rộng `RE_ANNEX_BLOCK_START` + safety net → phụ lục về body |
| Nghị quyết + Quy định kèm theo: hai `Điều 1` cùng path | Thiếu heading `QUY ĐỊNH` | `["QUY ĐỊNH", "Điều 1"]` vs `["Điều 1"]` |
| QUY ĐỊNH: Điều 1+2 gộp một chunk | Điều inline `.\n. Điều 2.` | Hai chunk riêng `["QUY ĐỊNH","Điều 1"]`, `["QUY ĐỊNH","Điều 2"]` |
| Chunk `part` chỉ tiêu đề QUY ĐỊNH (~50 token) | Header tách khỏi Điều 1 | Một `article` gồm header + Điều 1 |
| Điều 4: `Điều 4.\n100.000\nII Chi...` | Overlap + lặp tiêu đề | `clause_group` theo mục, không số lẻ đầu chunk |
| Điều 4 bảng chi: nhiều chunk `article` cắt giữa câu | Chỉ split theo câu `;` | `clause_group` theo mục Roman (`_ROMAN`) |
| Phụ lục OCR: nhóm XI. không tách trên 1 dòng pipe | Roman hard-code tới `X.` | Explode dùng `_ROMAN` (tới XX) |
| Câu cắt sau `UBND.` / `TW.` | Thiếu protect viết tắt | `split_sentences_vi` + `_RE_AUTO_ABBREV` |
| Chunk kết thúc `1.` / `3.`; `fallback_text`, `section_path=["Thân văn bản"]` | `split_sentences_vi` cắt tại khoản | `_RE_CLAUSE_NUMBER` + `RE_NUMBERED_CLAUSE_*` → `["Khoản N"]` |
| Bảng trong Điều 2: `section_path=["Điều 1"]` | `is_probably_table_line` trước `_parse_heading` | `table` tại `["Điều 2"]` |
| Footer sở/ngành không tách chữ ký | Thiếu chức danh | Thêm vào `_SIG_PATTERNS` |

---

## 6. Kết luận và hướng phát triển

Chiến lược chunking được thiết kế đặc thù cho văn bản pháp luật Việt Nam, ưu tiên giữ nguyên đơn vị nghĩa (Điều, khoản, bảng thủ tục) thay vì cắt theo kích thước cố định. Bộ đánh giá gồm 8 cell cung cấp cái nhìn toàn diện về chất lượng chunking trên 100 văn bản đa dạng.

Hướng phát triển tiếp theo:

- **Tích hợp với pipeline indexing**: Chunk output sẽ được đưa vào Qdrant (dense) và Elasticsearch (BM25).
- **LightRAG**: Sử dụng `relationships.parquet` để xây dựng đồ thị văn bản, kết hợp với `parent_id` trong chunk để mở rộng ngữ cảnh.
- **Mở rộng pattern**: Khi gặp loại văn bản mới (ví dụ: Bản án, Quyết định cá biệt), chỉ cần bổ sung hằng số trong `chunk.py` §2b.
- **Tối ưu hiệu suất**: Chạy chunking song song trên Polars với partition theo `id`.

Tài liệu tham khảo bổ sung: `chunking_evaluation.md`.

---

## 7. Production gates trước full embedding

Không chạy full embedding nếu một trong các gate sau chưa đạt:

| Metric | Target |
| --- | --- |
| `dense_tiny_pct_lt50chars` | < 5% |
| `dense_hard_split_count` | < 100, tốt nhất 0 |
| `dense_oversized_3k_pct` | < 2% |
| `table_integrity_bad_pct` | < 10% lỗi parser thật |
| `raw_table_embed_false_pct` | 100% |
| `table_summary_embed_true_pct` | gần 100% |
| `procedure_record_has_column_names_pct` | > 95% |
| `table_summary_has_raw_table_link_pct` | 100% |

`batch_chunk.py` chạy `validate_chunk_invariants()` sau khi merge Parquet. Validation phải không có vi phạm cho `raw_table` embed, summary link, summary answer rule, dense hard split và dense prose >= 10k.

### 7.1. Quy tắc tiny và long prose

- Chunk prose/heading < 50 ký tự được merge vào chunk kế tiếp cùng `section_path` hoặc `parent_id`. Nếu không có candidate hợp lệ thì `embed=False`.
- `procedure_record` < 50 ký tự và `table_part` < 50 ký tự chỉ dùng keyword index.
- `signature` và `distribution_list` không embed, không keyword index.
- Hard-char split còn lại được giữ để không mất coverage nhưng bắt buộc `embed=False`, `keyword_index=True`.
- Mọi prose >= 10.000 ký tự bắt buộc `embed=False`.

### 7.2. Table multi-vector schema

Mọi bảng được lưu thành `raw_table` để làm nguồn dữ liệu chính xác và một `table_summary` rule-based để dense retrieve. Bảng TTHC còn sinh thêm `procedure_record`; bảng có cấu trúc lớn có thể sinh `table_part`.

| Field | Quy tắc |
| --- | --- |
| `table_id` | Hash ổn định từ `doc_id + section_path + table_position` |
| `raw_table_id` | `chunk_id` của raw table tương ứng |
| `summary_of` | Alias của `raw_table_id` trên summary |
| `source_table_hash` | Hash từ raw text + section path, dùng cho cache |
| `table_columns` | Tên cột truyền xuống procedure/table-part |
| `table_summary_schema_json` | Summary có cấu trúc, không phải văn bản LLM tự do |
| `answer_source` | Luôn là `raw_table` trên `table_summary` |
| `do_not_answer_from_summary` | Luôn `True` trên `table_summary` |

Summary schema:

```json
{
  "table_title": "...",
  "legal_context": "...",
  "table_purpose": "...",
  "main_columns": ["..."],
  "key_entities": ["..."],
  "lookup_intents": ["..."],
  "answer_source": "raw_table"
}
```

**Answer rule:** `table_summary` chỉ dùng để retrieve. Câu hỏi cần số liệu, mức phí, thời hạn, điều kiện, tên thủ tục hoặc mã/ngạch phải expand sang `raw_table` hoặc `procedure_record`.

### 7.3. Table integrity metrics

Evaluator không kiểm tra `table_summary` như bảng thô. Ba metric parser riêng:

- `raw_table_has_header_pct`: raw table có header ở phần đầu.
- `table_part_has_header_or_parent_header_pct`: table part có header hoặc `parent_id` trỏ về raw table có header.
- `procedure_record_has_column_context_pct`: record có `procedure_name` và column metadata/context.

Các baseline retrieval chưa được tính trong chunking stage: `table_QA_hit@10`, `exact_value_accuracy`, `summary_hallucination_rate`.
