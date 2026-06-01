# Chiến lược chunking cho RAG pháp luật Việt Nam

## 0. Mục tiêu

Đặc tả triển khai pipeline chunking cho input:

```python
Schema([("id", Int64), ("content", String), ("source", String)])  # legacy | legacy+data | data
```

Mục tiêu: chunk có tính pháp lý hoàn chỉnh, phục vụ Hybrid RAG (BM25, dense embedding, reranker, GraphRAG/lightRAG) — không chia đều theo token.

Dữ liệu cần xử lý: công văn, quyết định, NĐ, thông tư, NQ; văn bản cực ngắn/dài (đến ~30k ký tự); Chương/Mục/Điều/khoản/điểm; phụ lục, bảng Markdown, OCR/spacing lỗi nhẹ, dòng phân cách `---`/`______`.

---

## 1. Nguyên tắc

1. **Không fixed-size làm chiến lược chính** — chỉ fallback khi hết separator logic (tránh cắt Điều/khoản, tách thủ tục khỏi trạng thái pháp lý, phá bảng).
2. **Giữ đơn vị nghĩa pháp lý**: Điều (nếu không quá dài), khoản/nhóm khoản, thủ tục trong phụ lục, block bảng có header, căn cứ pháp lý, kết luận/thi hành.
3. **Metadata tách khỏi nội dung** — lưu riêng; khi embed có thể prepend `context_prefix` ngắn (xem mục 3).
4. **Parent-child retrieval**: index ở child (thủ tục, khoản); generation có thể expand parent (lĩnh vực, phụ lục, văn bản).

| Đặc điểm              | Xử lý                             |
| --------------------- | --------------------------------- |
| Header/metadata chuẩn | Extract trước khi chunk body      |
| Chương/Mục/Điều/...   | Split theo hierarchy              |
| Độ dài phân tán       | Adaptive theo block type          |
| Bảng `\|...\|`        | Nhận diện và xử lý riêng          |
| Phụ lục dài           | Phụ lục → lĩnh vực → row          |
| `---`, `______`       | Separator phụ                     |
| Nơi nhận              | `distribution_list`, tách riêng   |
| Văn bản cực ngắn      | Giữ nguyên, `short_text`          |
| Dẫn chiếu             | `legal_references` trong metadata |

---

## 2. Output schema

```python
{
    "chunk_id": str, "doc_id": str | int, "source": str,
    "chunk_text": str,           # hiển thị/citation — không prepend metadata dài
    "contextual_text": str,      # embed/search — có prefix metadata ngắn
    "chunk_type": str,           # preamble | legal_basis | article | clause_group |
                                 # appendix | table | table_part | procedure_record |
                                 # distribution_list | signature | short_text | fallback_text
    "chunk_level": str,          # document | part | chapter | section | article | clause |
                                 # appendix | table | row | field
    "title", "doc_type", "agency", "doc_number", "issued_date": str | None,
    "section_path": list[str], "section": str | None,
    "appendix", "field", "subfield", "procedure_name": str | None,
    "legal_references": list[str],
    "parent_id", "prev_chunk_id", "next_chunk_id": str | None,
    "token_estimate": int,
    "quality_flags": list[str],
}
```

**`contextual_text`** (khuyến nghị):

```text
[Văn bản: Quyết định 1762/QĐ-UBND | Cơ quan: UBND tỉnh Bạc Liêu | Ngày: 29/09/2017 | Phụ lục: 1 | Lĩnh vực: Tư pháp]

<chunk_text>
```

Prefix ≤ 300–500 ký tự; rút gọn `section_path` nếu cần.

---

## 3. Pipeline

```text
content → normalize → extract doc metadata → detect layout → structural blocks
→ xử lý theo block type → merge/split adaptive → contextual_text → validate → export
```

### 3.1. Normalize

- `\r\n` → `\n`; strip dòng; collapse >3 dòng trắng → 2; giữ bảng Markdown.
- Không lowercase toàn văn bản; không xóa dấu/số thứ tự/Điều/Khoản/Phụ lục.
- OCR spacing: version đầu ưu tiên giữ nguyên gốc; sửa nhẹ chỉ khi confidence cao.
- Lưu `char_start`/`char_end` trên text đã normalize.

### 3.2. Metadata document

Header thường trước: `QUYẾT ĐỊNH:`, `Điều 1.`, `Căn cứ`, `Kính gửi:`, `PHỤ LỤC`, `---`.

| Field         | Pattern gợi ý                                                   |
| ------------- | --------------------------------------------------------------- |
| `doc_number`  | `Số:\s*...`, `.../...`                                          |
| `issued_date` | `ngày ... tháng ... năm ...`, `dd/mm/yyyy`                      |
| `agency`      | `ỦY BAN`, `BỘ`, `TỔNG CỤC`, `SỞ`, `CHÍNH PHỦ`                  |
| `doc_type`    | `QUYẾT ĐỊNH`, `CÔNG VĂN`, `NGHỊ ĐỊNH`, `THÔNG TƯ`, `NGHỊ QUYẾT` |
| `title`       | Sau doc_type hoặc `V/v ...`                                     |

Regex fail → field `None`, `quality_flags: ["metadata_incomplete"]` — không drop document.

### 3.3. Structural split

Separator (cao → thấp): PHẦN → CHƯƠNG → MỤC → ĐIỀU → khoản `1.` → điểm `a)` → PHỤ LỤC → bảng `|` → `---`/`______`.

```text
(?im)^\s*(PHẦN|Phần)\s+([IVXLCDM]+|\d+|THỨ\s+\w+)
(?im)^\s*(CHƯƠNG|Chương)\s+([IVXLCDM]+|\d+)
(?im)^\s*(MỤC|Mục)\s+\d+
(?im)^\s*(ĐIỀU|Điều)\s+\d+[.:]?
(?im)^\s*\d+\.\s+
(?im)^\s*[a-zđ]\)\s+
(?im)^\s*(PHỤ LỤC|Phụ lục)\s*([IVXLCDM]+|\d+)?
```

Duy trì `section_path` (part/chapter/section/article/appendix/field/subfield); mỗi chunk inherit path hiện tại.

---

## 4. Xử lý theo loại block

### Config

```yaml
min_chars: 300
target_chars: 1600
max_chars: 2200
hard_max_chars: 3000
overlap_chars: 150 # chỉ prose khi split Điều/khoản dài
table_max_chars: 2000
table_row_mode_threshold: 2500
short_doc_threshold: 300
```

**Separator priority**: appendix/part/chapter/section/article → numbered_clause/alphabet_point → paragraph/sentence → character_window (fallback).

### Điều/khoản

- Điều ≤ `max_chars` → một chunk.
- Điều > `max_chars` → split khoản → điểm → câu/đoạn + overlap.
- Segment < `min_chars` → merge cùng parent; **không** merge khác Điều, khác row thủ tục, hoặc `Nơi nhận` vào điều khoản.

### Công văn

`Kính gửi` + header → `preamble`; căn cứ → `legal_basis`; mỗi ý `1.`, `2.` → chunk riêng nếu đủ dài; kết luận riêng; `Nơi nhận` → `distribution_list`. Công văn < 1200 ký tự → một chunk + metadata đầy đủ.

### Quyết định

`Căn cứ... Xét đề nghị...` → `legal_basis`; mỗi Điều → chunk (kể cả Điều chỉ ban hành phụ lục); phụ lục/signature/nơi nhận tách riêng.

### Phụ lục

Detect `PHỤ LỤC`/`Phụ lục I`; parent chunk mở đầu; split theo lĩnh vực hoặc bảng; mỗi thủ tục → `procedure_record`. Không giữ cả phụ lục dài một chunk.

### Bảng Markdown

Detect: `^\s*\|.*\|\s*$` (≥2 dòng liên tiếp).

| Kích thước       | Xử lý                                                                                              |
| ---------------- | -------------------------------------------------------------------------------------------------- |
| ≤ 2000 ký tự     | Giữ Markdown, `chunk_type=table`                                                                   |
| > 2000 ký tự     | Split theo row, lặp header                                                                         |
| Danh mục thủ tục | Mỗi row → `procedure_record` (text mô tả có tên thủ tục, cơ quan, phụ lục, lĩnh vực, bưu chính...) |

### Khác

- **Cực ngắn** (`< min_chars`): một chunk `short_text`, không merge document khác.
- **Nơi nhận**: `distribution_list`, tách khỏi nội dung chính.
- **Chữ ký** (`KT. CHỦ TỊCH`, ...): tách cuối văn bản, không merge Điều cuối.

### Overlap

| Type                                                                        | Overlap                                                 |
| --------------------------------------------------------------------------- | ------------------------------------------------------- |
| `article`, `clause_group`, `fallback_text`                                  | 100–250 ký tự, kết thúc tại `.` `;` `:` hoặc xuống dòng |
| `table`, `procedure_record`, `short_text`, `distribution_list`, `signature` | Không overlap; bảng lặp header                          |

### Legal references

Extract per chunk: Luật, Nghị định/Thông tư/Quyết định/Công văn/Nghị quyết số ..., Khoản/Điểm/Điều — phục vụ BM25, citation, GraphRAG.

---

## 5. Retrieval (tương thích chunking)

| Thành phần | Field / ghi chú                                                                             |
| ---------- | ------------------------------------------------------------------------------------------- |
| Dense      | `contextual_text`                                                                           |
| BM25       | `chunk_text`, `title`, `doc_number`, `section_path`, `procedure_name`, `legal_references`  |
| Filter     | `source`, `doc_type`, `agency`, `issued_date`, `appendix`, `field`, `chunk_type`, ...       |
| Rerank     | `contextual_text` hoặc Title/Section/Content                                                |
| Expand     | `procedure_record` → parent appendix/field; `clause_group` → article; `table_part` → header |

---

## 6. Validation

**Metrics**: `total_documents`, `total_chunks`, `avg_chars_per_chunk`, p50/p90/p95/max, counts theo `chunk_type`, missing `doc_id`/`source`/`section_path`, `token_estimate` distribution.

**Flags**: `oversized_chunk`, `tiny_chunk`, `broken_table`, `metadata_incomplete`, `orphan_child`, `low_information`, `possible_ocr_noise`.

**Ngưỡng chấp nhận**: 0 chunk rỗng; 0 mất `doc_id`/`source`; <2% oversized; <5% tiny (trừ `short_text`/`signature`/`distribution_list`); bảng giữ header; `procedure_record` có `procedure_name`.

---

## 7. Test cases tối thiểu

| Case         | Input / điều kiện          | Expected                                                                         |
| ------------ | -------------------------- | -------------------------------------------------------------------------------- |
| Cực ngắn     | `"Toàn quốc"`              | 1 chunk `short_text`                                                             |
| QĐ + phụ lục | Điều 1, 2 + PHỤ LỤC 1      | `legal_basis`, `article`×2, appendix/procedure chunks, `section_path` có phụ lục |
| Điều dài     | Điều > max_chars, có khoản | Split khoản, path chứa tên Điều                                                  |
| Bảng thủ tục | Row karaoke X/X            | `procedure_record`, `procedure_name`, postal flags                               |
| Bảng dài     | >2500 ký tự                | Không cắt row; header lặp hoặc `procedure_record`                                |
| Nơi nhận     | Cuối VB                    | `distribution_list`, không merge Điều                                            |

---

## 8. Triển khai

**Phase 1 (MVP)**: normalize, metadata cơ bản, split Điều/khoản/phụ lục, bảng Markdown, schema + context prefix.

**Phase 2**: `procedure_record`, legal references, parent-child, distribution/signature, validation report.

**Phase 3**: tune size theo eval, hybrid BM25+dense, reranker, parent expansion.

**Quyết định cuối**: Legal structure-aware adaptive chunking + table/procedure parser + schema metadata-rich + `contextual_text` + parent-child + validation.

**Router block type**:

```text
short document      → short_text
article legal text  → article/clause
QĐ/NĐ/TT            → legal structure
appendix            → appendix (field → row)
markdown table      → table hoặc procedure_record
unknown long text   → paragraph/sentence fallback
```

Không dùng một splitter duy nhất cho toàn corpus.
