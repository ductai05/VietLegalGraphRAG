# Chiến lược chunking cho RAG pháp luật Việt Nam

## 0. Mục tiêu

Pipeline chunking nhận **content** (nội dung văn bản) và tuỳ chọn **metadata** (nhãn cấp văn bản từ catalog). Quan hệ giữa văn bản (`relationships.parquet`) **không** nhân bản trên từng chunk — dùng khi build graph / expand văn bản liên quan.

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

Mục tiêu: chunk có tính pháp lý hoàn chỉnh, phục vụ Hybrid RAG (BM25, dense embedding, reranker, GraphRAG/lightRAG) — không chia đều theo token.

---

## 1. Nguyên tắc

1. **Không fixed-size làm chiến lược chính** — chỉ fallback khi hết separator logic.
2. **Giữ đơn vị nghĩa pháp lý**: Điều, khoản/nhóm khoản, thủ tục trong phụ lục, block bảng, căn cứ, nơi nhận/chữ ký tách riêng.
3. **Metadata cấp văn bản (document-level)** lấy từ `metadata.parquet` — join `doc_id`, không parse header trên `content`.
4. **Parent-child retrieval (truy hồi cha-con trong cùng văn bản)**: index ở child (`procedure_record`, `clause_group`); expand qua `parent_id`.
5. **Không hard-code theo từng văn bản** (ví dụ tách thủ công Điều 1 / Điều 2). Mở rộng corpus bằng **pattern + hằng số tập trung** trong `chunk.py` mục **§2b** — không sửa logic chunker cho từng case.

| Đặc điểm              | Xử lý                                      |
| --------------------- | ------------------------------------------ |
| Nhãn văn bản          | Join `metadata.parquet` khi chunk / index   |
| Chương/Mục/Điều/...   | `section_path` từ structural split          |
| Vai trò nội dung      | `chunk_type` (article, procedure_record, …) |
| Bảng `\|...\|`        | `table` / `procedure_record` / `table_part` (có guard, xem §4.2) |
| Quy định đính kèm     | Heading khối đính kèm (`QUY ĐỊNH`, `DANH MỤC`, …) → cấp Phần trong `section_path` |
| Quan hệ giữa VB       | `relationships.parquet` (không trên chunk)  |

---

## 2. Output schema (chunk)

Chỉ lưu trường **gắn với đơn vị truy hồi (retrieval unit)**. Filter theo loại VB, cơ quan, hiệu lực → join `metadata` lúc query hoặc lúc build index.

```python
{
    "chunk_id": str,
    "doc_id": str | int,
    "source": str,

    "chunk_text": str,           # citation — không prepend metadata dài
    "contextual_text": str,      # embed — prefix ngắn từ metadata + section_path

    "chunk_type": str,           # preamble | legal_basis | article | clause_group |
                                 # appendix | table | table_part | procedure_record |
                                 # distribution_list | signature | short_text | fallback_text

    "section_path": list[str],   # vị trí trong văn bản: Phần/Chương/Điều/Phụ lục/...
    "procedure_name": str | None,  # chỉ khi chunk_type = procedure_record (tên TTHC trong bảng)

    "parent_id": str | None,     # expand trong cùng doc (clause → Điều, row → phụ lục)
    "prev_chunk_id": str | None,
    "next_chunk_id": str | None,

    "token_estimate": int,
    "quality_flags": list[str],
}
```

**Không lưu trên chunk** (join `metadata.parquet` theo `doc_id`): `title`, `legal_type`, `document_number`, `issuing_authority`, `issuance_date`, `effect_status`, `linh_vuc`, …

**`contextual_text`** — prefix ≤ 500 ký tự, build từ metadata đã join + `section_path` + `procedure_name`:

```text
[Văn bản: QUYẾT ĐỊNH 1762/QĐ-UBND - Về ban hành Danh mục... | Cơ quan: UBND tỉnh Bạc Liêu | Ngày ban hành: 29/09/2017 | Mục: Phụ lục 1 > I. Tư pháp]

<chunk_text>
```

---

## 3. Pipeline

```text
content (+ metadata join theo id)
  → normalize (inline Điều, explode pipe OCR)
  → structural blocks + section_path
  → xử lý theo chunk_type
  → merge/split adaptive (khoản / Roman / câu / char fallback)
  → contextual_text (prefix từ metadata)
  → validate → export chunks.parquet
```

Implementation: `pipeline/03_preprocessing/chunk.py` — hằng số mở rộng tại **§2b** trong file.

### 3.1. Normalize

- `\r\n` → `\n`; strip dòng; collapse >3 dòng trắng → 2; giữ bảng Markdown.
- Không lowercase toàn văn bản; không xóa dấu/số Điều/Khoản/Phụ lục.
- Chuẩn hóa khoảng trắng quanh `|` để parser bảng ổn định hơn.
- **Tách văn bản hỗn hợp một dòng** (`_explode_mixed_prose_and_tables`, chạy trước explode bảng):
  - `Nơi nhận:` inline sau `./.` → xuống dòng (`RE_FOOTER_INLINE`).
  - `DANH MỤC` / `PHỤ LỤC` sau dấu `.` hoặc `)` → xuống dòng, tách khỏi thân/ chữ ký.
  - Dòng dài vừa có marker pháp lý (`Điều`, `Căn cứ`, `QUYẾT ĐỊNH` ở đầu đoạn) vừa có lưới `| STT |` → cắt tại annex hoặc hàng lưới đầu tiên.
- **Tách Điều inline (OCR)**: `...)\n. Điều 2.`, `) . Điều 2.`, `QUYẾT ĐỊNH: Điều 1.`, và `...đính kèm. Điều 2.` (`RE_INLINE_ARTICLE_AFTER_PERIOD`) → heading `Điều N.` riêng. Pattern áp dụng cho **mọi** số Điều (`RE_INLINE_ARTICLE_*`), không theo `doc_id`.
- **Tách dòng bảng OCR dẹt** (`_explode_flattened_pipe_tables`): dòng dài (≥800 ký tự, ≥12 `|`) được tách thành nhiều dòng; nhóm mục/phụ lục dùng pattern Roman chung `_ROMAN` (I–XX).
- **Tách khoản Arabic inline** (`RE_INLINE_NUMBERED_CLAUSE`): `…; 2. Bộ chỉ huy…` → xuống dòng (Chỉ thị, Nghị quyết không có `Điều`, OCR một dòng).
- **Footer inline**: `RE_FOOTER` khớp `Nơi nhận` giữa dòng; `_extract_footer` đưa `DANH MỤC`/`PHỤ LỤC`/lưới pipe sau chữ ký trở lại **body** (không nuốt phụ lục vào khối footer).

### 3.2. Metadata văn bản

- Đọc từ `metadata.parquet` qua `doc_id` (hàm `coerce_document_metadata`, `chunk_polars_dataframe(..., metadata_df=...)`).
- Không regex header trên `content` — tránh trùng và lệch so với catalog.
- Thiếu metadata → prefix chỉ còn `section_path` / `source`; chunk vẫn được tạo.

### 3.3. Structural split

Separator (cao → thấp):

1. PHỤ LỤC → PHẦN → CHƯƠNG → MỤC
2. **Khối văn bản đính kèm** (một dòng, `RE_REGULATION_BLOCK` / `REGULATION_PART_IDS`):  
   `QUY ĐỊNH`, `QUY CHẾ`, `NỘI QUY`, `ĐIỀU LỆ`, `QUY TẮC`, `BẢNG GIÁ`, `DANH MỤC`, `PHƯƠNG ÁN`, `ĐỀ ÁN`, `CHƯƠNG TRÌNH` — xử lý như **Phần** (reset Chương/Mục/Điều; `section_path` ví dụ `["QUY ĐỊNH", "Điều 3"]` hoặc `["DANH MỤC", "Điều 1"]`). Sau split, **gộp** block `part` (tiêu đề khối đính kèm) với **Điều đầu tiên** kèm theo → một chunk `article`, tránh `tiny_chunk` chỉ header.
3. ĐIỀU (đầu dòng, sau normalize inline) → khoản `1.` → mục La Mã trong Điều (`_ROMAN`, xem §4.1)
3b. **Khoản cấp văn bản** (`RE_NUMBERED_CLAUSE_HEADING`): dòng `1. …` / `2. …` khi **không** đang trong block `Điều` (`in_article` chỉ bật nếu `section_path` hiện tại là `Điều N`) → `section_path` dạng `["Khoản 1"]`, xử lý như `article` (Chỉ thị, Nghị quyết chỉ có khoản). Khoản `N.` **bên trong** một `Điều` vẫn gom trong block Điều, tách bằng `_split_article_into_clauses`.
4. Trong **phụ lục**: nhóm lĩnh vực `I. …` / `Lĩnh vực:` — nhận qua `_parse_appendix_group_heading` + `_is_heading_text()` (all-caps hoặc keyword trong `_APPENDIX_HEADING_KEYWORDS`)
5. Bảng dòng có `|` (sau khi qua guard §4.2)
6. Footer: `Nơi nhận` → tách distribution / chữ ký theo `_SIG_PATTERNS` (§3.4)

Mỗi chunk có `section_path` kế thừa hierarchy hiện tại. **`chunk_type`** mô tả vai trò nội dung (không thay cho path).

### 3.4. Hằng số mở rộng (`chunk.py` §2b)

Logic chunker dùng **regex cấu trúc** (Điều, Chương, khoản, Roman) cho mọi văn bản. Các trường hợp đặc thù domain được cấu hình tập trung — **chỉ thêm vào list/frozenset**, không viết `if doc_id == …`.

| Hằng số | Mục đích | Cách mở rộng |
| -------- | -------- | ------------- |
| `_SENTENCE_SPLIT_PROTECTED` | Viết tắt hỗn hợp / 1 ký tự trước khi `split_sentences_vi` (`ThS.`, `v.v.`, `P.`, …) | Thêm cặp `"X.": "X<dot>"` |
| `_RE_AUTO_ABBREV` | Tự bảo vệ mọi `ALLCAPS≥2.` (`UBND.`, `TW.`, `HĐND.`, `NĐ.`, …) | Thường không cần sửa |
| `_RE_CLAUSE_NUMBER` | Bảo vệ khoản `1.` `2.` trước chữ hoa khi `split_sentences_vi` | Chỉ sửa nếu false positive mới (ví dụ `năm 12. Tháng`) |
| `RE_INLINE_NUMBERED_CLAUSE` | Tách khoản inline OCR (`; 2. Bộ…`) | Pattern chung, không theo `doc_id` |
| `RE_NUMBERED_CLAUSE_HEADING` | Heading `Khoản N` khi không có `Điều` | Cùng guard `in_article` trong `_parse_heading` |
| `_SIG_PATTERNS` | Tách chữ ký trong footer (`CHỦ TỊCH`, `CỤC TRƯỞNG`, `VIỆN TRƯỞNG`, …) | Thêm regex `\bCHỨC\s+DANH\b` |
| `_TTHC_DETECT_KEYWORDS` | Nhận bảng TTHC | Thêm substring lowercase |
| `_TTHC_HEADER_KEYWORDS` | Tìm hàng header bảng | Thêm substring |
| `_TTHC_HEADER_REJECT_KEYWORDS` | Bỏ hàng header khi parse row | Thêm substring |
| `_TABLE_SUBFIELD_PATTERNS` | Hàng nhóm `Lĩnh vực:` / `Ngành:` trong bảng | Thêm regex capture group |
| `_APPENDIX_HEADING_KEYWORDS` | Phân biệt tiêu đề nhóm vs dòng dữ liệu trong phụ lục | Thêm token UPPER |
| `REGULATION_PART_IDS` | Gộp header khối đính kèm với Điều 1 | Thêm id UPPER + cập nhật `RE_REGULATION_BLOCK` |

**Không** nằm trong §2b (đã generalize bằng pattern): số Điều (`RE_ARTICLE`), khoản Arabic (`RE_CLAUSE`), mục Roman (`_ROMAN` / `RE_ROMAN_SECTION_*`), tách Điều inline (`RE_INLINE_ARTICLE_*`).

---

## 4. Xử lý theo loại block

### Config

```yaml
min_chars: 300
target_chars: 1600
max_chars: 2200
hard_max_chars: 3000
overlap_chars: 150
table_max_chars: 2000
table_row_mode_threshold: 2500
short_doc_threshold: 300
```

### 4.1. Điều / khoản / phụ lục

- Điều ≤ `max_chars` → một chunk `article`.
- Điều dài → tách theo **khoản** `1.`, `2.`, … → `clause_group` (có `overlap_chars` giữa các nhóm).
- Điều rất dài **không có khoản Arabic** nhưng có **mục La Mã** (bảng biểu OCR dạng text): tách tại pattern `_ROMAN` (I, II, … XX) → `clause_group`:
  - **Không** `smart_overlap` giữa các mục (tránh kéo `100.000`, `50.000` sang chunk sau).
  - Chỉ chunk **đầu** của Điều mang dòng tiêu đề `Điều N.`; các `clause_group` sau bắt đầu trực tiếp bằng mục `II`, `III`, …
  - Bỏ dòng chỉ là mức tiền (`orphan amount`) ở đầu/cuối khi ghép overlap (nếu có).
- Vẫn vượt `max_chars` sau khi tách khoản/mục → `_split_prose` → `split_sentences_vi` → `hard_char_split` (flag `hard_char_split`).

**Tách câu (`split_sentences_vi`)** — dùng khi `_split_prose`, không phải chiến lược chính:

1. Bảo vệ viết tắt trong `_SENTENCE_SPLIT_PROTECTED` (hỗn hợp hoa-thường: `ThS.`, `v.v.`, `P.`, …).
2. Bảo vệ tự động mọi `([A-ZÀ-Ỵ]{2,}).` → không cắt sau `UBND.`, `TW.`, `HĐND.`, `NĐ.`, …
3. Bảo vệ khoản đánh số `(\b\d{1,2})\.\s+(?=[A-ZÀ-ỴĐ])` → không cắt sau `1.` trước `Chủ tịch…` (Chỉ thị, Nghị quyết, …).
4. Split tại `.!?;:` + khoảng trắng + chữ hoa/số; khôi phục placeholder.

Mở rộng viết tắt đặc biệt: chỉ sửa `_SENTENCE_SPLIT_PROTECTED` (§3.4); không hard-code theo từng văn bản.

### 4.2. Nhận dạng bảng (`|`)

Một dòng được coi là **dòng bảng** khi:

- Có cả `SỐ TT` và `THỦ TỤC` (header TTHC); hoặc
- Là **hàng lưới OCR** (`_is_pipe_grid_row`): bắt đầu bằng `| STT |` / `| 01 |` / `| I |`; hoặc
- Có ≥ **6** pipe **và** độ dài trung bình segment ≤ **120**; hoặc có ≥ **10** pipe.

**Không** coi là bảng (giữ `preamble` / `article`):

- Letterhead/chữ ký: ≤ **8** pipe nhưng có segment dài > **150** ký tự (`BỘ XÂY DỰNG | CỘNG HÒA... | Hà Nội...`).
- Thân văn bản: có `Điều N` / `Căn cứ` / loại văn bản ở **đầu đoạn** (`QUYẾT ĐỊNH`, `CHỈ THỊ`, … — **không** khớp nhầm từ “Quyết định” trong tên thủ tục bảng), ≤ **10** pipe, segment dài > **80**.

**Phụ lục + bảng trên một dòng**: `_split_annex_heading_line` tách `Phụ lục:` / `DANH MỤC` trước khi gom lưới pipe → `section_path` đúng (`Phụ lục`, `DANH MỤC`), không gán nhầm vào `Điều` cuối.

### 4.3. Bảng thủ tục / bảng lớn / footer

**Bảng TTHC** (`parse_procedure_tables: true` trong config):

- Nhận diện: substring trong `_TTHC_DETECT_KEYWORDS` **hoặc** (≥3 hàng STT số **và** văn bản chứa “thủ tục”). **Không** parse `procedure_record` chỉ vì bảng có cột STT (danh mục sản phẩm, biểu giá, …) — các bảng đó → `table` / `table_part`.
- Parse row: bỏ header theo `_TTHC_HEADER_REJECT_KEYWORDS`; nhóm lĩnh vực qua `_detect_major_field_row` / `_detect_sub_field_row` (`_TABLE_SUBFIELD_PATTERNS`, `_is_heading_text`).
- Output: `procedure_record` + `procedure_name` (một dòng TTHC = một chunk).
- Thêm loại bảng domain khác (phí, mức phạt): mở rộng keyword/pattern ở §2b hoặc plugin detector riêng — **không** nhánh `if` theo `doc_id`.

**Bảng markdown khác**

- Bảng lớn → `table` hoặc `table_part` (row mode khi vượt `table_row_mode_threshold`).

**Footer**

- Tách tại `Nơi nhận:` (`RE_FOOTER`).
- Trong khối footer: vị trí chữ ký tìm bằng `_SIG_PATTERNS` (KT./TM., CHỦ TỊCH, BỘ TRƯỞNG, CỤC TRƯỞNG, VIỆN TRƯỞNG, …) → `distribution_list` + `signature`.
- Thiếu pattern chức danh → cả khối gom `distribution_list`.

---

## 5. Retrieval

| Thành phần | Field / ghi chú |
| ---------- | --------------- |
| Dense      | `contextual_text` |
| BM25       | `chunk_text`, `section_path`, `procedure_name` |
| Filter doc | Join `metadata`: `legal_type`, `issuing_authority`, `effect_status`, `linh_vuc`, … |
| Filter chunk | `chunk_type`, `source`, phần tử trong `section_path` |
| Rerank     | `contextual_text` |
| Expand trong doc | `parent_id` (`procedure_record` → phụ lục/Điều; `clause_group` → Điều) |
| Graph giữa VB | `relationships.parquet` + `doc_id` |

---

## 6. Validation

**Metrics**: `total_chunks`, phân bố `chunk_type`, `section_path` rỗng, `token_estimate`, thiếu `procedure_name` trên `procedure_record`.

**Flags**: `oversized_chunk`, `tiny_chunk`, `hard_char_split`, `short_document`, …

**Ngưỡng**: 0 chunk rỗng; <2% oversized; `procedure_record` phải có `procedure_name`.

**Sanity check thủ công** (mẫu đã gặp):

| Triệu chứng | Nguyên nhân thường gặp | Kỳ vọng sau fix |
| ----------- | ---------------------- | --------------- |
| Công văn 1 chunk `table`, `section_path=["Thân văn bản"]` | `\|` letterhead trên 1 dòng | `preamble` (hoặc prose), không `table` |
| QĐ + danh mục: chỉ `procedure_record`, mất Điều 1–3 | OCR 1 dòng; `\|` letterhead; footer nuốt phụ lục; STT bảng → nhầm TTHC | `preamble` + `article` + `table` tại `DANH MỤC`/`Phụ lục` |
| Bảng TTHC: mất `procedure_record` | “Quyết định” trong tên thủ tục kích hoạt guard prose | Hàng `\| 01 \| …` vẫn là bảng; TTHC giữ `procedure_record` |
| Nghị quyết + Quy định kèm theo: hai `Điều 1` cùng path | Thiếu heading `QUY ĐỊNH` | `["QUY ĐỊNH", "Điều 1"]` vs `["Điều 1"]` |
| QUY ĐỊNH: Điều 1+2 gộp một chunk | Điều inline `.\n. Điều 2.` | Hai chunk `["QUY ĐỊNH","Điều 1"]`, `["QUY ĐỊNH","Điều 2"]` |
| Chunk `part` chỉ tiêu đề QUY ĐỊNH (~50 token) | Header tách khỏi Điều 1 | Một `article` gồm header + Điều 1 |
| Điều 4: `Điều 4.\n100.000\nII Chi...` | Overlap + lặp tiêu đề | `clause_group` theo mục, không số lẻ đầu chunk |
| Điều 4 bảng chi: nhiều chunk `article` cắt giữa câu | Chỉ split theo câu `;` | `clause_group` theo mục Roman (`_ROMAN`) |
| Phụ lục OCR: nhóm XI. không tách trên 1 dòng pipe | Roman hard-code tới `X.` | Explode dùng `_ROMAN` (tới XX) |
| Câu cắt sau `UBND.` / `TW.` | Thiếu protect viết tắt | `split_sentences_vi` + `_RE_AUTO_ABBREV` |
| Chunk kết thúc `1.` / `3.`; `fallback_text`, `section_path=["Thân văn bản"]` | `split_sentences_vi` cắt tại khoản; không nhận Chỉ thị `1. 2. 3.` | `_RE_CLAUSE_NUMBER` + `RE_NUMBERED_CLAUSE_*` → `["Khoản N"]`, `article` |
| Footer sở/ngành không tách chữ ký | Thiếu chức danh | Thêm vào `_SIG_PATTERNS` |

Khi gặp case mới: ưu tiên thêm pattern/keyword vào **§3.4**, chạy lại chunk corpus; tránh sửa logic theo `doc_id`.

---

## 7. API (Polars)

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

## 8. Router block type

```text
short document           → short_text
preamble / công văn      → preamble (kể cả dòng dài có | letterhead)
article legal text       → article / clause_group
  └ Điều dài + mục Roman (_ROMAN) → clause_group (Roman split, không prose-first)
Nghị quyết + khối đính kèm → part (QUY ĐỊNH | DANH MỤC | …) gộp Điều 1 → article / clause_group
  └ path: [<KHỐI ĐÍNH KÈM>, Điều N]
QĐ/NĐ/TT                 → legal structure (preamble, article, …)
Chỉ thị / NQ chỉ khoản   → preamble + Khoản 1/2/3 (`RE_NUMBERED_CLAUSE_HEADING`, không `Điều`)
appendix                 → appendix → appendix_group (heading keywords) → procedure_record (row)
markdown table (guard)   → table / table_part / procedure_record (TTHC keywords)
footer                   → distribution_list | signature (_SIG_PATTERNS)
unknown long text        → split_sentences_vi → fallback_text | hard_char_split
```

Không dùng một splitter cố định cho toàn corpus. Mở rộng hành vi: **§3.4** (`chunk.py` §2b), không patch theo từng `doc_id`.
