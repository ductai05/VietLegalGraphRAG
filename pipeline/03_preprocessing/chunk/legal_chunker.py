import re
import uuid
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 1. CONFIG
# ============================================================

@dataclass
class ChunkingConfig:
    min_chars: int = 300
    target_chars: int = 1600
    max_chars: int = 2200
    hard_max_chars: int = 3000

    overlap_chars: int = 150          # chỉ prose khi split Điều/khoản dài
    table_max_chars: int = 2000
    table_row_mode_threshold: int = 2500  # bảng > ngưỡng này → split từng row
    short_doc_threshold: int = 300

    max_context_prefix_chars: int = 500
    max_section_title_chars: int = 180

    parse_procedure_tables: bool = True

    # Long prose splitting (article/block > threshold → hierarchical split)
    long_prose_threshold: int = 3000     # chars > này với prose block → split tiếp
    long_prose_target_chars: int = 1400  # target khi hierarchical split (800–1800)
    long_prose_max_chars: int = 2500     # hard max sau hierarchical split
    table_summary_threshold: int = 3000  # bảng > này → table_summary + raw_table
    table_summary_max_chars: int = 1000  # cap độ dài table_summary (embed target)
    table_summary_max_columns: int = 12   # OCR 1 hàng nhiều cột — không liệt kê hết
    tiny_dense_char_limit: int = 50
    small_table_threshold: int = 500
    long_prose_no_embed_threshold: int = 10000


CONFIG = ChunkingConfig()


# ============================================================
# 2. REGEX HELPERS
# ============================================================

RE_WHITESPACE = re.compile(r"[ \t]+")
RE_MULTI_NEWLINE = re.compile(r"\n{3,}")

RE_APPENDIX = re.compile(
    r"^\s*(PHỤ\s+LỤC|Phụ\s+lục)\s*([IVXLCDM]+|\d+)?(?:\s*[:.\-–]\s*(.*))?$",
    re.IGNORECASE
)
RE_PART = re.compile(
    r"^\s*(PHẦN|Phần)\s+([IVXLCDM]+|\d+)(?:\s*[:.\-–]\s*(.*))?$",
    re.IGNORECASE
)
RE_CHAPTER = re.compile(
    r"^\s*(CHƯƠNG|Chương)\s+([IVXLCDM]+|\d+)(?:\s*[:.\-–]\s*(.*))?$",
    re.IGNORECASE
)
RE_SECTION = re.compile(
    r"^\s*(MỤC|Mục)\s+([IVXLCDM]+|\d+)(?:\s*[:.\-–]\s*(.*))?$",
    re.IGNORECASE
)
RE_ARTICLE = re.compile(
    r"^\s*(ĐIỀU|Điều)\s+(\d+[a-zA-Z]?)\s*[\.:]?\s*(.*)$",
    re.IGNORECASE
)
RE_CLAUSE = re.compile(r"^\s*(\d+)\.\s+")

# Roman numeral section headers inside long articles (e.g. fee-schedule tables extracted
# without pipe separators).  Only uppercase to avoid false matches on content words.
# Matches: "II Chi cho..." or "VIII\n..." (standalone numeral on its own line).
_ROMAN = r"(?:XIV|XIII|XII|XIX|XVIII|XVII|XVI|XV|XI|IX|VIII|VII|VI|IV|III|II|XX|X|V)"
RE_ROMAN_SECTION_INLINE = re.compile(rf"^\s*({_ROMAN})\s+[A-ZÀ-Ỵ]")
RE_ROMAN_SECTION_STANDALONE = re.compile(rf"^\s*({_ROMAN})\s*$")

RE_FOOTER = re.compile(
    r"(?is)(?:^|\s)(Nơi\s+nhận\s*[:\-].*)$",
)

# Embedded sub-document headers (e.g. attached regulations/bylaws inside a Nghị quyết).
# Treated as "part"-level heading so subsequent Điều numbers get a disambiguated section_path.
RE_REGULATION_BLOCK = re.compile(
    r"^\s*(QUY\s*ĐỊNH|QUY\s*CHẾ|NỘI\s*QUY|ĐIỀU\s*LỆ|QUY\s*TẮC"
    r"|BẢNG\s*GIÁ|DANH\s*MỤC|PHƯƠNG\s*ÁN|ĐỀ\s*ÁN|CHƯƠNG\s*TRÌNH)\s*$",
    re.IGNORECASE,
)

# Khối văn bản đính kèm (QUY ĐỊNH kèm Nghị quyết, …) — dùng khi gộp header với Điều đầu.
REGULATION_PART_IDS = frozenset({
    "QUY ĐỊNH", "QUY CHẾ", "NỘI QUY", "ĐIỀU LỆ", "QUY TẮC",
    "BẢNG GIÁ", "DANH MỤC", "PHƯƠNG ÁN", "ĐỀ ÁN", "CHƯƠNG TRÌNH",
})

# Điều không ở đầu dòng (OCR): "...HĐND)\n. Điều 2. Phạm vi..."
RE_INLINE_ARTICLE_AFTER_NEWLINE = re.compile(
    r"\n\s*\.\s*(Điều\s+\d+[a-zA-Z]?)\s*([\.\:])\s*",
    re.IGNORECASE,
)
RE_INLINE_ARTICLE_AFTER_PAREN = re.compile(
    r"(?<=[)])\s*\.\s+(Điều\s+\d+[a-zA-Z]?)\s*([\.\:])\s*",
    re.IGNORECASE,
)
# OCR: "QUYẾT ĐỊNH: Điều 1. Phê duyệt..." — tiêu đề kết luận + Điều trên cùng dòng
RE_INLINE_ARTICLE_AFTER_COLON = re.compile(
    r"(?<=[:\：])\s+(Điều\s+\d+[a-zA-Z]?)\s*([\.\:])\s*",
    re.IGNORECASE,
)
# OCR một dòng: "...đính kèm. Điều 2. Sở Nông nghiệp..."
RE_INLINE_ARTICLE_AFTER_PERIOD = re.compile(
    r"(?<=\.)\s+(Điều\s+\d+[a-zA-Z]?)\s*([\.\:])\s*",
    re.IGNORECASE,
)

RE_ANNEX_BLOCK_START = re.compile(
    r"\b(DANH\s+MỤC|PHỤ\s+LỤC"
    r"|ĐỀ\s+ÁN|ĐIỀU\s+LỆ|QUY\s+CHẾ|NỘI\s+QUY"
    r"|Biểu\s+số\s+\d+)\b",
    re.IGNORECASE,
)

# Footer trên cùng dòng với thân văn bản (không có xuống dòng trước "Nơi nhận")
RE_FOOTER_INLINE = re.compile(
    r"(?<=[./])\s+(Nơi\s+nhận\s*[:\-])",
    re.IGNORECASE,
)

# Bắt đầu lưới bảng pipe OCR: "| 1 |", "| A | Lĩnh vực", ...
RE_PIPE_GRID_ROW = re.compile(
    r"\s+\|\s+(?:\d{1,4}|[IVXLCDM]{1,6}|[A-ZÀ-Ỵ])\s+\|",
    re.IGNORECASE,
)

# Khoản Arabic đầu dòng / inline (Chỉ thị, Nghị quyết không có Điều: 1. … 2. … 3. …)
RE_NUMBERED_CLAUSE_HEADING = re.compile(r"^\s*(\d{1,2})\.\s+(.{3,})$")
RE_NUMBERED_CLAUSE_BODY_START = re.compile(r"^[A-ZÀ-ỴĐ]")
RE_INLINE_NUMBERED_CLAUSE = re.compile(
    r"(?<=[.;:\)）])\s+(\d{1,2})\.\s+(?=[A-ZÀ-ỴĐ])",
)

# Điểm a) b) c) đầu dòng trong khoản (chữ thường kể cả đ, sau normalize)
RE_DIEM_START = re.compile(r"(?m)(?=^[ \t]*[a-zđ][)\.]\s)", re.UNICODE)
# Nhận diện văn bản có cấu trúc luật (Điều, Chương) — dùng để detect appendix sub-doc
RE_HAS_ARTICLE_MARKER = re.compile(
    r"(?m)^\s*(ĐIỀU|Điều)\s+\d+|^\s*(CHƯƠNG|Chương)\s+[IVXLCDM\d]",
    re.IGNORECASE,
)


# ============================================================
# 2b. GENERALIZABLE CONSTANTS  (mở rộng tại đây, không sửa logic)
# ============================================================

# --------------- Tách câu ---------------
# Viết tắt hỗn hợp hoa-thường / 1 ký tự: không bị bảo vệ bởi auto-protect ALLCAPS.
# Viết tắt ALLCAPS ≥2 ký tự (UBND, TW, CP, NĐ, QĐ, HĐND, …) được bảo vệ tự động
# bởi _RE_AUTO_ABBREV bên dưới — không cần liệt kê ở đây.
_SENTENCE_SPLIT_PROTECTED: Dict[str, str] = {
    # Đơn vị hành chính 1 ký tự
    "P.": "P<dot>",
    "Q.": "Q<dot>",
    "H.": "H<dot>",
    # Học hàm / học vị hỗn hợp hoa-thường
    "ThS.": "ThS<dot>",
    "PGS.": "PGS<dot>",
    "TS.": "TS<dot>",
    "GS.": "GS<dot>",
    "BS.": "BS<dot>",
    "KS.": "KS<dot>",
    "CN.": "CN<dot>",
    "LS.": "LS<dot>",
    # Viết tắt thông dụng hỗn hợp / nhiều dấu chấm
    "v.v.": "vv<dot>",
    "v.v": "vv2<dot>",
    "Đ/c.": "Dc<dot>",
}

# Bảo vệ tự động mọi chuỗi ALLCAPS ≥2 ký tự trước dấu chấm (UBND., TW., NĐ., …).
# [A-ZÀ-Ỵ] bao gồm ASCII uppercase + toàn bộ uppercase có dấu tiếng Việt (Đ, Ă, Ơ, …).
_RE_AUTO_ABBREV = re.compile(r"([A-ZÀ-Ỵ]{2,})\.")
_AUTO_ABBREV_PH = "<adot>"   # placeholder khác với <dot> để tránh collision khi restore

# Khoản đánh số 1. 2. 3. — không cắt tại dấu chấm khi split câu (Chỉ thị, Nghị quyết, …).
_CLAUSE_NUMBER_PH = "<cdot>"
_RE_CLAUSE_NUMBER = re.compile(r"(\b\d{1,2})\.\s+(?=[A-ZÀ-ỴĐ])")

# --------------- Chữ ký cuối văn bản ---------------
# Thêm chức danh mới tại đây mà không cần sửa _extract_footer.
_SIG_PATTERNS: List[str] = [
    r"\bKT\.\s+",
    r"\bTM\.\s+",
    r"\bCHỦ\s+TỊCH\b",
    r"\bPHÓ\s+CHỦ\s+TỊCH\b",
    r"\bBỘ\s+TRƯỞNG\b",
    r"\bTHỨ\s+TRƯỞNG\b",
    r"\bTỔNG\s+GIÁM\s+ĐỐC\b",
    r"\bGIÁM\s+ĐỐC\b",
    r"\bPHÓ\s+GIÁM\s+ĐỐC\b",
    r"\bTỔNG\s+CỤC\s+TRƯỞNG\b",
    r"\bCỤC\s+TRƯỞNG\b",
    r"\bVỤ\s+TRƯỞNG\b",
    r"\bCHÁNH\s+VĂN\s+PHÒNG\b",
    r"\bTRƯỞNG\s+BAN\b",
    r"\bHIỆU\s+TRƯỞNG\b",
    r"\bTRƯỞNG\s+PHÒNG\b",
    r"\bVIỆN\s+TRƯỞNG\b",
    r"\bCHÁNH\s+ÁN\b",
    r"\bTHỦ\s+TRƯỞNG\b",
    r"\bTRƯỞNG\s+CƠ\s+QUAN\b",
]

# --------------- Bảng thủ tục hành chính (TTHC) ---------------
# Từ khóa nhận diện bảng TTHC — thêm loại bảng mới tại đây.
_TTHC_DETECT_KEYWORDS: frozenset = frozenset({
    "thủ tục hành chính", "tên thủ tục", "tthc",
})
# Từ khóa nhận diện hàng tiêu đề bảng TTHC.
_TTHC_HEADER_KEYWORDS: frozenset = frozenset({
    "thủ tục", "tên thủ tục", "số tt", "số thứ tự",
})
# Từ khóa nhận diện hàng header/separator cần bỏ qua khi parse record.
_TTHC_HEADER_REJECT_KEYWORDS: frozenset = frozenset({
    "tên thủ tục", "số tt", "ghi chú", "số thứ tự",
})
# Pattern nhận diện cột phân nhóm lĩnh vực trong bảng (sub-field rows).
_TABLE_SUBFIELD_PATTERNS: List[str] = [
    r"(Lĩnh\s+vực\s*[:\-]?\s*.+)",
    r"(Ngành\s*[:\-]?\s*.+)",
]

# --------------- Tiêu đề nhóm trong phụ lục ---------------
# Từ khóa phân biệt dòng heading nhóm lĩnh vực (I. LĨNH VỰC TƯ PHÁP)
# với dòng dữ liệu bình thường khi cả hai đều bắt đầu bằng Roman numeral.
# Thêm domain keyword mới tại đây.
_APPENDIX_HEADING_KEYWORDS: frozenset = frozenset({
    "TTHC", "LĨNH VỰC", "NHÓM LĨNH VỰC", "THỦ TỤC HÀNH CHÍNH",
    "NGÀNH", "PHÂN NHÓM", "LOẠI",
})

# --------------- Retrieval index flags ---------------
# Chunk types KHÔNG embed vào dense vector index.
_NO_EMBED_TYPES: frozenset = frozenset({
    "raw_table", "signature", "distribution_list",
})
# Chunk types KHÔNG index BM25/keyword search.
_NO_BM25_TYPES: frozenset = frozenset({
    "signature", "distribution_list",
})


def get_retrieval_flags(chunk_type: str) -> Tuple[bool, bool]:
    """Trả về (embed, keyword_index) cho chunk_type đã cho."""
    return (
        chunk_type not in _NO_EMBED_TYPES,
        chunk_type not in _NO_BM25_TYPES,
    )


def _meaningful_table_headers(rows: List[List[str]]) -> List[str]:
    if not rows:
        return []
    return [
        cell.strip()
        for cell in rows[0]
        if cell.strip() and cell.strip() not in {"-", "--", "---"}
    ]


# ============================================================
# 3. NORMALIZER
# ============================================================

class LegalTextNormalizer:
    @staticmethod
    def normalize(text: str) -> str:
        if not text:
            return ""

        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\u00a0", " ")
        text = text.replace("−", "-").replace("–", "-").replace("—", "-")

        lines = []
        for line in text.split("\n"):
            line = RE_WHITESPACE.sub(" ", line).strip()
            lines.append(line)

        text = "\n".join(lines)
        text = RE_MULTI_NEWLINE.sub("\n\n", text)

        # Chuẩn hóa khoảng trắng quanh dấu pipe để parser bảng ổn hơn.
        # Không dùng \s ở đây vì nó nuốt luôn newline và làm phẳng toàn bộ bảng.
        text = re.sub(r"[ \t]*\|[ \t]*", " | ", text)
        text = re.sub(r"[ \t]{2,}", " ", text)

        text = LegalTextNormalizer._explode_mixed_prose_and_tables(text)
        text = LegalTextNormalizer._explode_flattened_pipe_tables(text)
        text = LegalTextNormalizer._explode_inline_articles(text)
        text = LegalTextNormalizer._explode_inline_numbered_clauses(text)

        return text.strip()

    @staticmethod
    def _explode_mixed_prose_and_tables(text: str) -> str:
        """Tách phụ lục/danh mục, footer và lưới bảng khỏi thân văn bản trên cùng một dòng OCR."""
        text = RE_FOOTER_INLINE.sub(r"\n\1", text)

        def split_annex(m: re.Match) -> str:
            return "\n" + m.group(0)

        text = re.sub(
            r"(?<=[)])\s+(?=(?:DANH\s+MỤC|PHỤ\s+LỤC)\b)",
            split_annex,
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"(?<=\.)\s+(?=(?:DANH\s+MỤC|PHỤ\s+LỤC)\b)",
            split_annex,
            text,
            flags=re.IGNORECASE,
        )

        new_lines: List[str] = []
        for line in text.split("\n"):
            if (
                len(line) > 400
                and line.count("|") >= 3
                and _line_has_legal_prose_markers(line)
            ):
                grid = RE_PIPE_GRID_ROW.search(line)
                annex = RE_ANNEX_BLOCK_START.search(line)
                split_at = None
                if annex and annex.start() > 80:
                    split_at = annex.start()
                elif grid and grid.start() > 80:
                    split_at = grid.start()
                if split_at is not None:
                    head = line[:split_at].strip()
                    tail = line[split_at:].strip()
                    if head:
                        new_lines.append(head)
                    if tail:
                        new_lines.append(tail)
                    continue
            new_lines.append(line)
        return "\n".join(new_lines)

    @staticmethod
    def _explode_inline_articles(text: str) -> str:
        """Tách Điều nằm giữa đoạn (sau dấu chấm / xuống dòng / dấu hai chấm) thành dòng heading riêng."""
        text = RE_INLINE_ARTICLE_AFTER_COLON.sub(r"\n\1\2 ", text)
        text = RE_INLINE_ARTICLE_AFTER_PERIOD.sub(r"\n\1\2 ", text)
        text = RE_INLINE_ARTICLE_AFTER_NEWLINE.sub(r"\n\1\2 ", text)
        text = RE_INLINE_ARTICLE_AFTER_PAREN.sub(r"\n\1\2 ", text)
        return text

    @staticmethod
    def _explode_inline_numbered_clauses(text: str) -> str:
        """Tách khoản 1. 2. 3. nằm giữa đoạn (OCR một dòng) thành dòng riêng."""
        return RE_INLINE_NUMBERED_CLAUSE.sub(r"\n\1. ", text)

    @staticmethod
    def _explode_flattened_pipe_tables(text: str) -> str:
        new_lines = []
        for line in text.split("\n"):
            if len(line) > 800 and line.count("|") >= 12:
                s = line
                s = re.sub(
                    r"\s+\|\s*(?=(?:\d{1,4}|[IVXLCDM]{1,6}\.|[A-ZÀ-Ỵ]\.)\s*\|)",
                    "\n| ",
                    s
                )
                s = re.sub(
                    rf"\s+(?=(?:PHỤ\s+LỤC|{_ROMAN}\.)\s+[A-ZÀ-Ỵ])",
                    "\n",
                    s
                )
                new_lines.extend([x.strip() for x in s.split("\n") if x.strip()])
            else:
                new_lines.append(line)
        return "\n".join(new_lines)


# ============================================================
# 4. DOCUMENT METADATA (from metadata.parquet, join by doc id)
# ============================================================

METADATA_PREFIX_FIELDS = (
    "title",
    "legal_type",
    "document_number",
    "issuing_authority",
    "issuance_date",
    "effect_status",
    "linh_vuc",
)


def coerce_document_metadata(record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Chuẩn hóa một dòng metadata.parquet cho prefix ngữ cảnh khi embed."""
    if not record:
        return {}
    out: Dict[str, Any] = {}
    for key in METADATA_PREFIX_FIELDS:
        val = record.get(key)
        if val is not None and str(val).strip():
            out[key] = str(val).strip()
    return out


def metadata_lookup_from_dataframe(metadata_df, id_col: str = "id") -> Dict[Any, Dict[str, Any]]:
    """Map doc id → metadata dict (Polars hoặc pandas DataFrame)."""
    try:
        records = metadata_df.to_dicts()
    except AttributeError:
        records = metadata_df.to_dict(orient="records")
    return {rec[id_col]: coerce_document_metadata(rec) for rec in records}


# ============================================================
# 5. UTILS
# ============================================================

def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def make_uuid() -> str:
    return str(uuid.uuid4())


def truncate(value: Optional[str], max_len: int) -> Optional[str]:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= max_len:
        return value
    return value[:max_len - 3] + "..."


def _pipe_line_stats(line: str) -> Tuple[int, float, int]:
    """(pipe_count, avg_segment_len, max_segment_len)"""
    segments = [seg.strip() for seg in line.split("|") if seg.strip()]
    if not segments:
        return line.count("|"), float(len(line)), len(line)
    lengths = [len(seg) for seg in segments]
    return line.count("|"), sum(lengths) / len(lengths), max(lengths)


def _line_has_legal_prose_markers(line: str) -> bool:
    """Đánh dấu thân văn bản — không khớp 'Quyết định' trong tên thủ tục bảng."""
    if re.search(r"\b(Điều\s+\d+[a-zA-Z]?|Căn\s+cứ)\b", line, re.IGNORECASE):
        return True
    return bool(
        re.search(
            r"(?:^|[.;:]\s*)"
            r"(QUYẾT\s*ĐỊNH|CHỈ\s*THỊ|NGHỊ\s*QUYẾT|THÔNG\s*TƯ|CÔNG\s*VĂN)\b",
            line,
            re.IGNORECASE,
        )
    )


def _is_pipe_grid_row(line: str) -> bool:
    """Hàng lưới OCR: | STT | nội dung | ..."""
    s = line.strip()
    if s.count("|") < 2:
        return False
    return bool(
        re.match(
            r"^\|?\s*(?:\d{1,4}|[IVXLCDM]{1,6}|[A-ZÀ-Ỵ])\s+\|",
            s,
            re.IGNORECASE,
        )
    )


def is_probably_table_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False

    if re.search(r"\bSỐ\s*TT\b", s, re.IGNORECASE) and re.search(
        r"\bTHỦ\s*TỤC\b", s, re.IGNORECASE
    ):
        return True

    if _is_pipe_grid_row(s):
        return True

    pipe_count, avg_segment_len, max_segment_len = _pipe_line_stats(s)
    if pipe_count < 2:
        return False

    # Letterhead / chữ ký: ít cột pipe, có đoạn prose dài — không phải hàng bảng.
    if pipe_count <= 8 and max_segment_len > 150:
        return False

    # Thân văn bản (Điều, căn cứ, …) lẫn vài pipe letterhead — giữ prose.
    if _line_has_legal_prose_markers(s) and pipe_count <= 10 and max_segment_len > 80:
        return False

    # Lưới bảng OCR: nhiều pipe hoặc ô ngắn đều nhau.
    if pipe_count >= 6 and avg_segment_len <= 120:
        return True
    if pipe_count >= 10:
        return True

    if avg_segment_len > 200:
        return False

    return pipe_count >= 2 and avg_segment_len <= 200


def split_sentences_vi(text: str) -> List[str]:
    s = text
    # Bước 1: bảo vệ viết tắt hỗn hợp / 1 ký tự trong danh sách tường minh.
    for k, v in _SENTENCE_SPLIT_PROTECTED.items():
        s = s.replace(k, v)
    # Bước 2: bảo vệ tự động mọi chuỗi ALLCAPS ≥2 ký tự trước dấu chấm
    # (UBND., TW., CP., NĐ., HĐND., VKSND., … — không cần liệt kê từng cái).
    s = _RE_AUTO_ABBREV.sub(r"\1" + _AUTO_ABBREV_PH, s)
    # Bước 3: bảo vệ khoản đánh số (1. Chủ tịch …) — tránh cắt sau "1."
    s = _RE_CLAUSE_NUMBER.sub(r"\1" + _CLAUSE_NUMBER_PH + " ", s)

    parts = re.split(r"(?<=[.!?;:])\s+(?=[A-ZÀ-Ỵ0-9Đ])", s)
    out = []
    for p in parts:
        # Khôi phục bước 1
        for k, v in _SENTENCE_SPLIT_PROTECTED.items():
            p = p.replace(v, k)
        # Khôi phục bước 2
        p = p.replace(_AUTO_ABBREV_PH, ".")
        # Khôi phục bước 3
        p = p.replace(_CLAUSE_NUMBER_PH, ".")
        p = p.strip()
        if p:
            out.append(p)
    return out


def is_orphan_amount_line(line: str) -> bool:
    """Dòng chỉ là mức tiền (đuôi bảng biểu OCR) — không dùng làm overlap."""
    s = line.strip()
    if not s:
        return False
    if re.fullmatch(r"-?[\d.,]+\s*000(?:\.\d{3})*", s):
        return True
    if re.fullmatch(r"-?[\d.,]{4,18}", s) and "." in s:
        return True
    return False


def strip_leading_orphan_amounts(text: str) -> str:
    lines = text.split("\n")
    while lines and is_orphan_amount_line(lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip()


def strip_trailing_orphan_amounts(text: str) -> str:
    lines = text.split("\n")
    while lines and is_orphan_amount_line(lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def clauses_use_roman_sections(clauses: List[str]) -> bool:
    for clause in clauses:
        first = clause.split("\n", 1)[0].strip()
        if RE_ROMAN_SECTION_INLINE.match(first) or RE_ROMAN_SECTION_STANDALONE.match(first):
            return True
    return False


def smart_overlap(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    tail = text[-max_chars:]

    candidates = [
        tail.rfind("\n"),
        tail.rfind(". "),
        tail.rfind("; "),
        tail.rfind(": "),
    ]
    idx = max(candidates)
    if idx >= 40:
        return tail[idx + 1:].strip()

    space_idx = tail.find(" ")
    if space_idx != -1:
        return tail[space_idx + 1:].strip()
    return tail.strip()


def normalize_heading_id(kind: str, number: Optional[str]) -> str:
    if number:
        return f"{kind} {number}".strip()
    return kind.strip()


def _group_text_items(items: List[str], max_chars: int) -> List[str]:
    """Gộp list các đoạn text thành nhóm không quá max_chars ký tự mỗi nhóm."""
    groups: List[str] = []
    current: List[str] = []
    current_len = 0
    for item in items:
        if current and current_len + len(item) + 1 > max_chars:
            groups.append("\n".join(current))
            current = [item]
            current_len = len(item)
        else:
            current.append(item)
            current_len += len(item) + 1
    if current:
        groups.append("\n".join(current))
    return groups


# ============================================================
# 7. MAIN CHUNKER
# ============================================================

class VietnameseLegalChunker:
    def __init__(
        self,
        doc_id: Any,
        content: str,
        source: str = "unknown",
        doc_metadata: Optional[Dict[str, Any]] = None,
        config: ChunkingConfig = CONFIG,
    ):
        self.doc_id = str(doc_id)
        self.raw_content = content or ""
        self.source = source
        self.config = config

        self.normalized_text = LegalTextNormalizer.normalize(self.raw_content)
        self.doc_metadata = coerce_document_metadata(doc_metadata)

        self.chunks: List[Dict[str, Any]] = []
        self._table_positions: Dict[str, int] = {}

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def chunk(self) -> List[Dict[str, Any]]:
        text = self.normalized_text.strip()
        if not text:
            return []

        if (
            len(text) < self.config.short_doc_threshold
            and not any(is_probably_table_line(line) for line in text.splitlines())
        ):
            self._emit_chunk(
                chunk_text=text,
                chunk_type="short_text",
                section_path=["Toàn văn"],
                parent_key=self._make_parent_key(["Toàn văn"]),
                quality_flags=["short_document"],
            )
            self._postprocess_chunks()
            self._finalize_links()
            return self.chunks

        body_text, footer_blocks = self._extract_footer(text)
        blocks = self._merge_regulation_header_blocks(self._split_into_blocks(body_text))

        for block in blocks:
            self._process_block(block)

        for block in footer_blocks:
            self._process_block(block)

        self._postprocess_chunks()
        self._finalize_links()
        return self.chunks

    # --------------------------------------------------------
    # Footer
    # --------------------------------------------------------

    def _extract_footer(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        m = RE_FOOTER.search(text)
        if not m:
            return text, []

        body = text[:m.start()].strip()
        footer = m.group(1).strip()

        # OCR: phụ lục/danh mục đính kèm sau khối chữ ký trong cùng "footer"
        annex_m = RE_ANNEX_BLOCK_START.search(footer)
        if annex_m and annex_m.start() > 0:
            body = f"{body}\n\n{footer[annex_m.start():].strip()}".strip()
            footer = footer[:annex_m.start()].strip()
        else:
            grid_m = RE_PIPE_GRID_ROW.search(footer)
            if grid_m and grid_m.start() > 20:
                body = f"{body}\n\n{footer[grid_m.start():].strip()}".strip()
                footer = footer[:grid_m.start()].strip()

        blocks = []

        sig_pos = None
        for pat in _SIG_PATTERNS:
            sm = re.search(pat, footer, re.IGNORECASE)
            if sm:
                sig_pos = sm.start()
                break

        footer_path = ["Thông tin bổ sung"]
        if sig_pos is not None and sig_pos > 20:
            dist = footer[:sig_pos].strip()
            sig = footer[sig_pos:].strip()
            if dist:
                blocks.append(self._make_block(dist, "distribution_list", "footer", footer_path + ["Nơi nhận"]))
            if sig:
                blocks.append(self._make_block(sig, "signature", "footer", footer_path + ["Ký tên"]))
        else:
            blocks.append(self._make_block(footer, "distribution_list", "footer", footer_path + ["Nơi nhận"]))

        return body, blocks

    # --------------------------------------------------------
    # Structural block splitting
    # --------------------------------------------------------

    def _split_into_blocks(self, text: str) -> List[Dict[str, Any]]:
        lines = text.split("\n")
        blocks: List[Dict[str, Any]] = []

        state: Dict[str, Any] = {
            "appendix": None,
            "part": None,
            "chapter": None,
            "section": None,
            "article": None,
            "major_field": None,
            "sub_field": None,
        }

        current_lines: List[str] = []
        current_type = "preamble"
        current_level = "document"
        current_path = ["Thân văn bản"]

        table_lines: List[str] = []
        in_table = False

        def current_section_path() -> List[str]:
            path = []
            for key in ["appendix", "part", "chapter", "section", "article", "major_field", "sub_field"]:
                if state.get(key):
                    path.append(state[key]["id"])
            return path or ["Thân văn bản"]

        def flush_current():
            nonlocal current_lines, current_type, current_level, current_path
            txt = "\n".join(current_lines).strip()
            if txt:
                blocks.append(self._make_block(
                    txt, current_type, current_level, current_path,
                ))
            current_lines = []

        def flush_table():
            nonlocal table_lines, in_table
            txt = "\n".join(table_lines).strip()
            if txt:
                blocks.append(self._make_block(
                    txt, "table", "table", current_section_path(),
                ))
            table_lines = []
            in_table = False

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                if in_table:
                    flush_table()
                current_lines.append("")
                continue

            annex_split = self._split_annex_heading_line(line)
            if annex_split:
                annex_heading, remainder = annex_split
                if in_table:
                    flush_table()
                flush_current()
                current_type, current_level = self._apply_heading_to_state(
                    annex_heading, state
                )
                current_path = current_section_path()
                if remainder:
                    line = remainder
                else:
                    continue

            in_dieu = bool(
                state.get("article")
                and str(state["article"]["id"]).lower().startswith("điều")
            )
            heading = self._parse_heading(line, in_article=in_dieu)
            if heading:
                if in_table:
                    flush_table()
                flush_current()
                current_type, current_level = self._apply_heading_to_state(
                    heading, state
                )
                current_path = current_section_path()
                if not is_probably_table_line(line):
                    current_lines.append(line)
                    continue

            if is_probably_table_line(line):
                if not in_table:
                    flush_current()
                    table_lines = []
                    in_table = True
                table_lines.append(line)
                continue

            if in_table:
                flush_table()

            group_heading = self._parse_appendix_group_heading(line)
            if group_heading and state.get("appendix"):
                flush_current()

                if group_heading["type"] == "major_field":
                    state["major_field"] = {"id": group_heading["id"], "title": group_heading["title"]}
                    state["sub_field"] = None
                    current_type, current_level = "appendix_group", "field"
                else:
                    state["sub_field"] = {"id": group_heading["id"], "title": group_heading["title"]}
                    current_type, current_level = "appendix_subgroup", "field"

                current_path = current_section_path()
                current_lines.append(line)
                continue

            current_lines.append(line)

        if in_table:
            flush_table()
        flush_current()

        return blocks

    def _merge_regulation_header_blocks(
        self, blocks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Gộp block part (QUY ĐỊNH + tiêu đề) với Điều đầu tiên — tránh chunk tiny chỉ header."""
        if not blocks:
            return blocks

        out: List[Dict[str, Any]] = []
        i = 0
        while i < len(blocks):
            b = blocks[i]
            if (
                b["type"] == "part"
                and len(b["section_path"]) == 1
                and b["section_path"][0] in REGULATION_PART_IDS
                and i + 1 < len(blocks)
                and blocks[i + 1]["type"] == "article"
            ):
                nxt = blocks[i + 1]
                out.append(self._make_block(
                    b["text"].strip() + "\n\n" + nxt["text"].strip(),
                    "article",
                    "article",
                    nxt["section_path"],
                ))
                i += 2
                continue
            out.append(b)
            i += 1
        return out

    def _split_annex_heading_line(
        self, line: str
    ) -> Optional[Tuple[Dict[str, str], str]]:
        """Tách tiêu đề Phụ lục/Danh mục khỏi phần bảng pipe còn lại trên cùng dòng."""
        m = re.match(
            r"^\s*(Phụ\s+lục|PHỤ\s+LỤC)\s*[:\-]?\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if m:
            rest = m.group(2).strip()
            return {
                "type": "appendix",
                "id": "Phụ lục",
                "title": truncate(rest or line, self.config.max_section_title_chars),
            }, rest

        m = re.match(
            r"^\s*(DANH\s+MỤC)\b\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if m:
            rest = m.group(2).strip()
            return {
                "type": "part",
                "id": "DANH MỤC",
                "title": truncate(rest or line, self.config.max_section_title_chars),
            }, rest

        return None

    def _apply_heading_to_state(
        self,
        heading: Dict[str, str],
        state: Dict[str, Any],
    ) -> Tuple[str, str]:
        h_type = heading["type"]
        h_id = heading["id"]
        h_title = heading["title"]

        if h_type == "appendix":
            state.update({
                "appendix": {"id": h_id, "title": h_title},
                "part": None,
                "chapter": None,
                "section": None,
                "article": None,
                "major_field": None,
                "sub_field": None,
            })
            return "appendix", "appendix"

        if h_type == "part":
            state.update({
                "part": {"id": h_id, "title": h_title},
                "chapter": None,
                "section": None,
                "article": None,
                "major_field": None,
                "sub_field": None,
            })
            return "part", "part"

        if h_type == "chapter":
            state.update({
                "chapter": {"id": h_id, "title": h_title},
                "section": None,
                "article": None,
            })
            return "chapter", "chapter"

        if h_type == "section":
            state.update({
                "section": {"id": h_id, "title": h_title},
                "article": None,
            })
            return "section", "section"

        if h_type == "article":
            state.update({
                "article": {"id": h_id, "title": h_title},
            })
            return "article", "article"

        return "preamble", "document"

    def _parse_heading(self, line: str, in_article: bool = False) -> Optional[Dict[str, str]]:
        for typ, pat, label in [
            ("appendix", RE_APPENDIX, "Phụ lục"),
            ("part", RE_PART, "Phần"),
            ("chapter", RE_CHAPTER, "Chương"),
            ("section", RE_SECTION, "Mục"),
        ]:
            m = pat.match(line)
            if m:
                number = m.group(2) if len(m.groups()) >= 2 else None
                title = m.group(3) if len(m.groups()) >= 3 else None
                return {
                    "type": typ,
                    "id": normalize_heading_id(label, number),
                    "title": truncate(title or line, self.config.max_section_title_chars),
                }

        m = RE_REGULATION_BLOCK.match(line)
        if m:
            block_name = re.sub(r"\s+", " ", m.group(1)).strip().upper()
            return {
                "type": "part",
                "id": block_name,
                "title": None,
            }

        m = re.match(
            r"^\s*(DANH\s+MỤC|PHỤ\s+LỤC)\b\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        if m:
            block_name = re.sub(r"\s+", " ", m.group(1)).strip().upper()
            title = (m.group(2) or "").strip() or None
            return {
                "type": "part",
                "id": block_name,
                "title": truncate(title, self.config.max_section_title_chars),
            }

        m = RE_ARTICLE.match(line)
        if m:
            number = m.group(2)
            title = m.group(3) or None
            return {
                "type": "article",
                "id": f"Điều {number}",
                "title": truncate(title, self.config.max_section_title_chars),
            }

        # Khoản 1. 2. 3. cấp văn bản (Chỉ thị, Nghị quyết không có Điều) — không nhầm khoản trong Điều.
        if not in_article:
            m = RE_NUMBERED_CLAUSE_HEADING.match(line)
            if m and RE_NUMBERED_CLAUSE_BODY_START.match(m.group(2).strip()):
                return {
                    "type": "article",
                    "id": f"Khoản {m.group(1)}",
                    "title": truncate(m.group(2).strip(), self.config.max_section_title_chars),
                }

        return None

    def _parse_appendix_group_heading(self, line: str) -> Optional[Dict[str, str]]:
        s = line.strip(" |")

        m = re.match(r"^([IVXLCDM]{1,6})\.\s+(.{3,})$", s, re.IGNORECASE)
        if m and len(s) <= 180:
            title = m.group(2).strip()
            if self._is_heading_text(title):
                return {
                    "type": "major_field",
                    "id": f"{m.group(1).upper()}. {truncate(title, 120)}",
                    "title": truncate(title, 120),
                }

        m = re.match(r"^\d+\.\s*(Lĩnh vực\s*[:\-]?\s*.+)$", s, re.IGNORECASE)
        if m and len(s) <= 180:
            title = m.group(1).strip()
            return {
                "type": "sub_field",
                "id": truncate(title, 140),
                "title": truncate(title, 140),
            }

        return None

    def _make_block(
        self,
        text: str,
        typ: str,
        level: str,
        section_path: List[str],
    ) -> Dict[str, Any]:
        return {
            "text": text.strip(),
            "type": typ,
            "level": level,
            "section_path": section_path or ["Thân văn bản"],
        }

    # --------------------------------------------------------
    # Block processing
    # --------------------------------------------------------

    def _process_block(self, block: Dict[str, Any]) -> None:
        text = block["text"].strip()
        if not text:
            return

        typ = block["type"]
        section_path = block["section_path"]

        if typ == "table":
            self._process_table(text, section_path)
            return

        if typ == "article":
            self._process_article(text, section_path)
            return

        if typ in {"distribution_list", "signature"}:
            # Safety net: sig/dist quá lớn → OCR đã nuốt appendix vào block này.
            # Cố gắng tách phần phụ lục ra và xử lý riêng.
            if len(text) > self.config.long_prose_threshold:
                annex_m = RE_ANNEX_BLOCK_START.search(text)
                if annex_m and annex_m.start() > 20:
                    actual_sig = text[:annex_m.start()].strip()
                    extra_content = text[annex_m.start():].strip()
                    if actual_sig:
                        self._emit_chunk(
                            chunk_text=actual_sig,
                            chunk_type=typ,
                            section_path=section_path,
                            parent_key=self._make_parent_key(section_path),
                        )
                    if extra_content:
                        self._parse_appendix_subdoc(extra_content, section_path)
                    return
            self._emit_chunk(
                chunk_text=text,
                chunk_type=typ,
                section_path=section_path,
                parent_key=self._make_parent_key(section_path),
            )
            return

        # Block prose lớn > long_prose_threshold
        if len(text) > self.config.long_prose_threshold:
            if self._has_legal_structure(text):
                # Appendix dạng văn bản (Điều lệ, Đề án, Quy chế, ...) → re-parse
                self._parse_appendix_subdoc(text, section_path)
            else:
                self._hierarchical_split_prose(
                    text=text,
                    chunk_type=self._chunk_type_for_split(typ),
                    section_path=section_path,
                    parent_key=self._make_parent_key(section_path),
                )
            return

        if len(text) <= self.config.max_chars:
            self._emit_chunk(
                chunk_text=text,
                chunk_type=typ,
                section_path=section_path,
                parent_key=self._make_parent_key(section_path),
            )
        else:
            self._split_prose(
                text=text,
                chunk_type=self._chunk_type_for_split(typ),
                section_path=section_path,
                parent_key=self._make_parent_key(section_path),
            )

    # --------------------------------------------------------
    # Article processing
    # --------------------------------------------------------

    def _process_article(self, text: str, section_path: List[str]) -> None:
        _, article_title = self._extract_article_id_title(text)
        parent_key = self._make_parent_key(section_path)

        if len(text) <= self.config.max_chars:
            self._emit_chunk(
                chunk_text=text,
                chunk_type="article",
                section_path=section_path,
                section_title=article_title,
                parent_key=parent_key,
            )
            return

        title_line, clauses = self._split_article_into_clauses(text)
        if not clauses:
            # Không tìm được khoản → hierarchical split nếu quá lớn
            if len(text) > self.config.long_prose_threshold:
                self._hierarchical_split_prose(
                    text=text,
                    chunk_type="article",
                    section_path=section_path,
                    parent_key=parent_key,
                    section_title=article_title,
                )
            else:
                self._split_prose(
                    text=text,
                    chunk_type="article",
                    section_path=section_path,
                    parent_key=parent_key,
                    section_title=article_title,
                )
            return

        roman_mode = clauses_use_roman_sections(clauses)
        use_overlap = not roman_mode
        first_emitted = True
        current: List[str] = []
        current_len = len(title_line)

        def _emit_group() -> None:
            nonlocal first_emitted
            body = "\n".join(current)
            chunk_text = (f"{title_line}\n{body}" if first_emitted else body).strip()
            first_emitted = False
            if len(chunk_text) > self.config.long_prose_max_chars:
                # Khoản gộp vẫn quá lớn → hierarchical split tiếp
                self._hierarchical_split_prose(
                    text=chunk_text,
                    chunk_type="clause_group",
                    section_path=section_path,
                    parent_key=parent_key,
                    section_title=article_title,
                )
            else:
                self._emit_chunk(
                    chunk_text=chunk_text,
                    chunk_type="clause_group",
                    section_path=section_path,
                    section_title=article_title,
                    parent_key=parent_key,
                )

        for clause in clauses:
            clause = strip_leading_orphan_amounts(clause)
            if not clause:
                continue

            if current and current_len + len(clause) > self.config.max_chars:
                _emit_group()

                if use_overlap:
                    overlap = strip_leading_orphan_amounts(
                        strip_trailing_orphan_amounts(
                            smart_overlap("\n".join(current), self.config.overlap_chars)
                        )
                    )
                    current = [overlap, clause] if overlap else [clause]
                else:
                    current = [clause]
                current_len = sum(len(x) for x in current) + (len(current) - 1)
            else:
                current.append(clause)
                current_len += len(clause) + 1

        if current:
            _emit_group()

    def _extract_article_id_title(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        first = text.split("\n", 1)[0].strip()
        m = RE_ARTICLE.match(first)
        if not m:
            return None, None
        return f"Điều {m.group(2)}", truncate(m.group(3) or None, self.config.max_section_title_chars)

    def _split_article_into_clauses(self, text: str) -> Tuple[str, List[str]]:
        lines = text.split("\n")
        title_line = lines[0]
        body_lines = lines[1:]

        clauses = []
        current = []

        for line in body_lines:
            stripped = line.strip()
            is_arabic = RE_CLAUSE.match(stripped) and current
            is_roman = (
                RE_ROMAN_SECTION_INLINE.match(stripped)
                or RE_ROMAN_SECTION_STANDALONE.match(stripped)
            ) and current
            if is_arabic or is_roman:
                clauses.append("\n".join(current).strip())
                current = [line]
            else:
                current.append(line)

        if current:
            clauses.append("\n".join(current).strip())

        if len(clauses) <= 1:
            return title_line, []

        return title_line, [c for c in clauses if c]

    # --------------------------------------------------------
    # Table processing
    # --------------------------------------------------------

    def _process_table(self, table_text: str, section_path: List[str]) -> None:
        parent_key = self._make_parent_key(section_path + ["Bảng"])
        table_key = f"{self.doc_id}::{' > '.join(section_path)}"
        table_position = self._table_positions.get(table_key, 0)
        self._table_positions[table_key] = table_position + 1
        table_id = stable_hash(f"{table_key}::{table_position}", length=24)
        source_table_hash = stable_hash(
            f"{table_text}::{' > '.join(section_path)}", length=40
        )
        rows = self._parse_pipe_rows(table_text)
        columns = self._infer_table_columns(rows)
        strategy = self._classify_table_strategy(table_text, rows)

        raw_chunk = self._emit_chunk(
            chunk_text=table_text,
            chunk_type="raw_table",
            section_path=section_path,
            parent_key=parent_key,
            table_id=table_id,
            source_table_hash=source_table_hash,
            table_columns=columns,
            table_strategy=strategy,
            answer_source="raw_table",
        )
        if raw_chunk is None:
            return
        raw_table_id = raw_chunk["chunk_id"]

        summary_schema = self._generate_table_summary_schema(
            table_text, section_path, rows=rows, strategy=strategy
        )
        summary = self._table_summary_contextual_text(summary_schema, table_text)
        self._emit_chunk(
            chunk_text=summary,
            chunk_type="table_summary",
            section_path=section_path,
            parent_key=parent_key,
            table_id=table_id,
            raw_table_id=raw_table_id,
            summary_of=raw_table_id,
            source_table_hash=source_table_hash,
            table_columns=columns,
            table_summary_schema=summary_schema,
            table_strategy=strategy,
            answer_source="raw_table",
            do_not_answer_from_summary=True,
        )

        # Bảng TTHC → raw_table + summary + procedure_record.
        if self.config.parse_procedure_tables and self._looks_like_procedure_table(table_text):
            records = self._parse_procedure_table_records(table_text, section_path, parent_key)
            if records:
                for rec in records:
                    self._emit_procedure_record(
                        rec,
                        section_path,
                        parent_key,
                        table_id=table_id,
                        raw_table_id=raw_table_id,
                        source_table_hash=source_table_hash,
                        table_columns=columns,
                    )
                return

        table_len = len(table_text)

        # Row-level/table-part retrieval bổ sung cho bảng trung bình/lớn có cấu trúc.
        if len(rows) > 4 and table_len > self.config.table_row_mode_threshold:
            self._split_large_table_rows(
                rows,
                section_path,
                parent_key,
                table_id=table_id,
                raw_table_id=raw_table_id,
                source_table_hash=source_table_hash,
                table_strategy=strategy,
            )

    def _classify_table_strategy(
        self, table_text: str, rows: List[List[str]]
    ) -> str:
        if self._looks_like_procedure_table(table_text):
            return "procedure_table"
        if len(table_text) < self.config.small_table_threshold:
            return "small_table"
        non_empty = [cell for row in rows[:20] for cell in row if cell.strip()]
        numeric_like = sum(
            bool(re.fullmatch(r"[\d\s.,/%+\-–—]+", cell.strip()))
            for cell in non_empty
        )
        if non_empty and numeric_like / len(non_empty) >= 0.5:
            return "numeric_or_code_table"
        if len(table_text) >= self.config.table_summary_threshold:
            return "large_table"
        return "structured_table"

    def _looks_like_procedure_table(self, text: str) -> bool:
        lower = text.lower()
        if not any(kw in lower for kw in _TTHC_DETECT_KEYWORDS):
            return False

        rows = self._parse_pipe_rows(text)
        if not rows:
            return True

        for row in rows[:8]:
            joined = " ".join(row).lower()
            if any(kw in joined for kw in _TTHC_HEADER_KEYWORDS):
                return True

        numeric_rows = 0
        for cells in rows:
            cells2 = [c for c in cells if c.strip()]
            if len(cells2) >= 2 and re.match(r"^\d{1,4}$", cells2[0].strip()):
                numeric_rows += 1
        return numeric_rows >= 3 and "thủ tục" in lower

    def _parse_pipe_rows(self, table_text: str) -> List[List[str]]:
        rows = []
        for raw in table_text.split("\n"):
            line = raw.strip()
            if not line or line.count("|") < 1:
                continue

            if re.match(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$", line):
                continue

            if "|" in line:
                parts = [c.strip() for c in line.strip().strip("|").split("|")]
                if any(parts):
                    rows.append(parts)

        return rows

    def _parse_procedure_table_records(
        self,
        table_text: str,
        section_path: List[str],
        parent_key: str,
    ) -> List[Dict[str, Any]]:
        rows = self._parse_pipe_rows(table_text)
        if not rows:
            return []

        current_major_field = self._infer_field_from_path(section_path)
        current_sub_field = None
        header_cells = self._find_header_cells(rows)

        records = []

        for cells in rows:
            cells_clean = [c.strip() for c in cells]
            non_empty = [c for c in cells_clean if c]

            if not non_empty:
                continue

            if self._is_header_like(cells_clean):
                continue

            major = self._detect_major_field_row(cells_clean)
            if major:
                current_major_field = major
                current_sub_field = None
                continue

            sub = self._detect_sub_field_row(cells_clean)
            if sub:
                current_sub_field = sub
                continue

            rec = self._parse_procedure_row(
                cells=cells_clean,
                header_cells=header_cells,
                major_field=current_major_field,
                sub_field=current_sub_field,
                section_path=section_path,
            )
            if rec:
                records.append(rec)

        return records

    def _find_header_cells(self, rows: List[List[str]]) -> List[str]:
        for row in rows[:6]:
            joined = " ".join(row).lower()
            if any(kw in joined for kw in _TTHC_HEADER_KEYWORDS):
                return row
        return []

    def _infer_table_columns(self, rows: List[List[str]]) -> List[str]:
        """Chọn header tốt nhất trong vài hàng đầu, thay vì mặc định hàng đầu là caption."""
        best: List[str] = []
        best_score = -1
        hints = ("stt", "tt", "mã", "tên", "nội dung", "thủ tục", "đơn vị", "ghi chú", "thời hạn")
        for row in rows[:6]:
            cells = _meaningful_table_headers([row])
            joined = " ".join(cells).lower()
            score = sum(hint in joined for hint in hints) * 10 + len(cells)
            if score > best_score:
                best = cells
                best_score = score
        return best[:self.config.table_summary_max_columns]

    def _is_header_like(self, cells: List[str]) -> bool:
        joined = " ".join(cells).lower()
        if not joined:
            return True
        if any(kw in joined for kw in _TTHC_HEADER_REJECT_KEYWORDS):
            return True
        if set(joined.replace(" ", "")) <= {"-", ":"}:
            return True
        return False

    def _detect_major_field_row(self, cells: List[str]) -> Optional[str]:
        non_empty = [c.strip(" .") for c in cells if c.strip()]
        if not non_empty:
            return None

        first = non_empty[0]
        joined = " ".join(non_empty)

        if re.match(r"^[IVXLCDM]{1,6}$", first, re.IGNORECASE) and len(non_empty) >= 2:
            candidate = " ".join(non_empty[1:])
            if self._is_heading_text(candidate):
                return truncate(candidate, 180)

        m = re.match(r"^([IVXLCDM]{1,6})\.\s+(.+)$", joined, re.IGNORECASE)
        if m:
            candidate = m.group(2).strip()
            if self._is_heading_text(candidate):
                return truncate(candidate, 180)

        return None

    @staticmethod
    def _is_heading_text(text: str) -> bool:
        """Heuristic: text là tiêu đề nhóm (all-caps hoặc chứa từ khóa domain)."""
        up = text.upper()
        if up == text:           # all-caps
            return True
        if any(kw in up for kw in _APPENDIX_HEADING_KEYWORDS):
            return True
        return False

    def _detect_sub_field_row(self, cells: List[str]) -> Optional[str]:
        joined = " ".join([c for c in cells if c.strip()])
        if len(joined) > 250:
            return None
        for pat in _TABLE_SUBFIELD_PATTERNS:
            m = re.search(pat, joined, re.IGNORECASE)
            if m:
                return truncate(m.group(1).strip(), 180)
        return None

    def _parse_procedure_row(
        self,
        cells: List[str],
        header_cells: List[str],
        major_field: Optional[str],
        sub_field: Optional[str],
        section_path: List[str],
    ) -> Optional[Dict[str, Any]]:
        non_empty = [c.strip() for c in cells if c.strip()]
        if len(non_empty) < 2:
            return None

        stt = None
        stt_idx = None
        for i, c in enumerate(cells):
            if re.match(r"^\d{1,4}$", c.strip()):
                stt = c.strip()
                stt_idx = i
                break

        if stt is None:
            return None

        candidates = []
        for i, c in enumerate(cells):
            cc = c.strip()
            if not cc or i == stt_idx:
                continue
            if re.fullmatch(r"[xX\-–—]+", cc):
                continue
            if len(cc) >= 8:
                candidates.append((i, cc))

        if not candidates:
            return None

        name_idx, procedure_name = max(candidates, key=lambda x: len(x[1]))

        after_name = cells[name_idx + 1:]
        status_cells = [c.strip() for c in after_name if c.strip()]

        has_receive = None
        has_return = None

        status_marks = []
        for c in status_cells:
            if re.fullmatch(r"[xX]", c):
                status_marks.append(True)
            elif re.fullmatch(r"[\-–—]", c):
                status_marks.append(False)

        if len(status_marks) >= 1:
            has_receive = status_marks[0]
        if len(status_marks) >= 2:
            has_return = status_marks[1]

        fields = {}
        if header_cells and len(header_cells) == len(cells):
            for h, v in zip(header_cells, cells):
                h = h.strip()
                v = v.strip()
                if h and v:
                    fields[h] = v

        return {
            "stt": stt,
            "procedure_name": procedure_name,
            "major_field": major_field,
            "sub_field": sub_field,
            "receive_by_post": has_receive,
            "return_by_post": has_return,
            "raw_cells": cells,
            "fields": fields,
            "section_path": section_path,
        }

    def _emit_procedure_record(
        self,
        rec: Dict[str, Any],
        section_path: List[str],
        parent_key: str,
        table_id: str,
        raw_table_id: str,
        source_table_hash: str,
        table_columns: List[str],
    ) -> None:
        lines = [
            f"Số thứ tự: {rec.get('stt')}",
            f"Tên thủ tục hành chính: {rec.get('procedure_name')}",
        ]

        if rec.get("major_field"):
            lines.append(f"Nhóm lĩnh vực: {rec['major_field']}")
        if rec.get("sub_field"):
            lines.append(f"Lĩnh vực: {rec['sub_field']}")

        if rec.get("receive_by_post") is not None:
            lines.append(f"Tiếp nhận hồ sơ qua bưu chính công ích: {'Có' if rec['receive_by_post'] else 'Không'}")
        if rec.get("return_by_post") is not None:
            lines.append(f"Trả kết quả qua bưu chính công ích: {'Có' if rec['return_by_post'] else 'Không'}")

        if rec.get("fields"):
            lines.append("Thông tin bảng gốc:")
            for k, v in rec["fields"].items():
                lines.append(f"- {k}: {v}")

        chunk_text = "\n".join(lines)

        record_path = list(section_path)
        if rec.get("major_field") and rec["major_field"] not in record_path:
            record_path.append(rec["major_field"])
        if rec.get("sub_field") and rec["sub_field"] not in record_path:
            record_path.append(rec["sub_field"])
        record_path.append(rec["procedure_name"])

        self._emit_chunk(
            chunk_text=chunk_text,
            chunk_type="procedure_record",
            section_path=record_path,
            section_title=rec.get("procedure_name"),
            parent_key=parent_key,
            procedure_name=rec.get("procedure_name"),
            parent_id=raw_table_id,
            table_id=table_id,
            raw_table_id=raw_table_id,
            source_table_hash=source_table_hash,
            table_columns=table_columns,
            table_strategy="procedure_table",
            answer_source="procedure_record",
        )

    def _split_large_table_rows(
        self,
        rows: List[List[str]],
        section_path: List[str],
        parent_key: str,
        table_id: str,
        raw_table_id: str,
        source_table_hash: str,
        table_strategy: str,
    ) -> None:
        if not rows:
            return

        header = rows[0]
        current_rows = []
        current_len = len(" | ".join(header))

        for row in rows[1:]:
            row_text = " | ".join(row)
            if current_rows and current_len + len(row_text) > self.config.table_max_chars:
                chunk_text = self._rows_to_markdown_like_table(header, current_rows)
                self._emit_chunk(
                    chunk_text=chunk_text,
                    chunk_type="table_part",
                    section_path=section_path,
                    parent_key=parent_key,
                    parent_id=raw_table_id,
                    table_id=table_id,
                    raw_table_id=raw_table_id,
                    source_table_hash=source_table_hash,
                    table_columns=self._infer_table_columns(rows),
                    table_strategy=table_strategy,
                    answer_source="raw_table",
                )
                current_rows = [row]
                current_len = len(" | ".join(header)) + len(row_text)
            else:
                current_rows.append(row)
                current_len += len(row_text) + 1

        if current_rows:
            chunk_text = self._rows_to_markdown_like_table(header, current_rows)
            self._emit_chunk(
                chunk_text=chunk_text,
                chunk_type="table_part",
                section_path=section_path,
                parent_key=parent_key,
                parent_id=raw_table_id,
                table_id=table_id,
                raw_table_id=raw_table_id,
                source_table_hash=source_table_hash,
                table_columns=self._infer_table_columns(rows),
                table_strategy=table_strategy,
                answer_source="raw_table",
            )

    def _rows_to_markdown_like_table(self, header: List[str], rows: List[List[str]]) -> str:
        out = [" | ".join(header)]
        for r in rows:
            out.append(" | ".join(r))
        return "\n".join(out)

    def _infer_field_from_path(self, section_path: List[str]) -> Optional[str]:
        for x in reversed(section_path):
            if "lĩnh vực" in x.lower():
                return x
            if re.search(r"\bTTHC\b", x, re.IGNORECASE):
                return x
        return None

    # --------------------------------------------------------
    # Prose splitting
    # --------------------------------------------------------

    def _split_prose(
        self,
        text: str,
        chunk_type: str,
        section_path: List[str],
        parent_key: str,
        section_title: Optional[str] = None,
    ) -> None:
        sentences = split_sentences_vi(text)

        if len(sentences) <= 1:
            soft_units = self._split_soft_legal_units(text)
            if len(soft_units) > 1:
                for group in _group_text_items(soft_units, self.config.long_prose_max_chars):
                    if len(group) <= self.config.long_prose_max_chars:
                        self._emit_chunk(
                            chunk_text=group,
                            chunk_type=chunk_type,
                            section_path=section_path,
                            section_title=section_title,
                            parent_key=parent_key,
                        )
                    else:
                        self._split_by_hard_chars(
                            group, chunk_type, section_path, parent_key, section_title
                        )
                return
            self._split_by_hard_chars(
                text=text,
                chunk_type=chunk_type,
                section_path=section_path,
                parent_key=parent_key,
                section_title=section_title,
            )
            return

        current = []
        current_len = 0

        for sent in sentences:
            if current and current_len + len(sent) > self.config.target_chars:
                chunk_text = " ".join(current).strip()
                self._emit_chunk(
                    chunk_text=chunk_text,
                    chunk_type=chunk_type,
                    section_path=section_path,
                    section_title=section_title,
                    parent_key=parent_key,
                )

                overlap = smart_overlap(chunk_text, self.config.overlap_chars)
                current = [overlap, sent] if overlap else [sent]
                current_len = sum(len(x) for x in current) + len(current)
            else:
                current.append(sent)
                current_len += len(sent) + 1

        if current:
            chunk_text = " ".join(current).strip()
            self._emit_chunk(
                chunk_text=chunk_text,
                chunk_type=chunk_type,
                section_path=section_path,
                section_title=section_title,
                parent_key=parent_key,
            )

    def _split_by_hard_chars(
        self,
        text: str,
        chunk_type: str,
        section_path: List[str],
        parent_key: str,
        section_title: Optional[str] = None,
    ) -> None:
        step = max(1, self.config.target_chars - self.config.overlap_chars)
        start = 0

        while start < len(text):
            end = min(len(text), start + self.config.target_chars)
            chunk_text = text[start:end].strip()
            if chunk_text:
                self._emit_chunk(
                    chunk_text=chunk_text,
                    chunk_type=chunk_type,
                    section_path=section_path,
                    section_title=section_title,
                    parent_key=parent_key,
                    quality_flags=["hard_char_split"],
                )
            start += step

    @staticmethod
    def _split_soft_legal_units(text: str) -> List[str]:
        """Fallback mềm cho OCR prose một dòng: điểm, bullet, mệnh đề và dấu chấm phẩy."""
        patterns = [
            r"(?=\s+[a-zđ][).]\s+)",
            r"(?=\s+[-+•]\s+)",
            r"(?=\s+(?:Trường hợp|Đối với|Căn cứ)\b)",
            r"(?<=;)\s+",
            r"\n+",
        ]
        parts = [text]
        for pattern in patterns:
            next_parts: List[str] = []
            for part in parts:
                next_parts.extend(re.split(pattern, part, flags=re.IGNORECASE))
            parts = [p.strip() for p in next_parts if p.strip()]
        return parts

    # --------------------------------------------------------
    # Hierarchical long-prose splitting
    # --------------------------------------------------------

    @staticmethod
    def _has_legal_structure(text: str) -> bool:
        """Kiểm tra text có chứa marker cấu trúc luật (Điều, Chương) để nhận sub-doc."""
        return bool(RE_HAS_ARTICLE_MARKER.search(text))

    @staticmethod
    def _split_by_diem(text: str) -> List[str]:
        """Tách điểm a) b) c) / a. b. c. đầu dòng — khoản con trong khoản."""
        parts = RE_DIEM_START.split(text)
        return [p.strip() for p in parts if p.strip()]

    def _hierarchical_split_prose(
        self,
        text: str,
        chunk_type: str,
        section_path: List[str],
        parent_key: str,
        section_title: Optional[str] = None,
    ) -> None:
        """
        Split theo thứ tự ưu tiên: điểm → paragraph → sentence → hard char.
        Dùng khi text > long_prose_threshold.
        Target: long_prose_target_chars; max mỗi chunk: long_prose_max_chars.
        """
        max_c = self.config.long_prose_max_chars

        def emit(t: str) -> None:
            self._emit_chunk(
                chunk_text=t.strip(),
                chunk_type=chunk_type,
                section_path=section_path,
                parent_key=parent_key,
                section_title=section_title,
            )

        def sentence_or_hard(t: str) -> None:
            if len(t) <= max_c:
                emit(t)
            else:
                self._split_prose(t, chunk_type, section_path, parent_key, section_title)

        if len(text) <= max_c:
            emit(text)
            return

        # Cấp 1: điểm a) b) c)
        diem_parts = self._split_by_diem(text)
        if len(diem_parts) > 1:
            for group in _group_text_items(diem_parts, max_c):
                sentence_or_hard(group)
            return

        # Cấp 2: paragraph (\n\n)
        paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paras) > 1:
            for group in _group_text_items(paras, max_c):
                sentence_or_hard(group)
            return

        # Cấp 3: sentence / hard char (fall through)
        self._split_prose(text, chunk_type, section_path, parent_key, section_title)

    # --------------------------------------------------------
    # Appendix sub-document re-parsing
    # --------------------------------------------------------

    def _parse_appendix_subdoc(self, text: str, section_path: List[str]) -> None:
        """
        Re-parse một appendix/phần lớn có cấu trúc luật (Điều lệ, Đề án, Quy chế)
        như sub-document. Tất cả chunk article/clause_group được gán chunk_type='appendix_text'.
        """
        parent_key = self._make_parent_key(section_path)
        start_idx = len(self.chunks)

        sub_blocks = self._merge_regulation_header_blocks(self._split_into_blocks(text))

        for sub_block in sub_blocks:
            sub_text = sub_block["text"]
            sub_type = sub_block["type"]
            if not sub_text:
                continue

            # Gộp section_path cha với sub-path (bỏ placeholder "Thân văn bản")
            sub_path = [p for p in sub_block["section_path"] if p != "Thân văn bản"]
            combined_path = list(section_path) + sub_path if sub_path else list(section_path)

            if sub_type == "table":
                self._process_table(sub_text, combined_path)
            elif sub_type in {"distribution_list", "signature"}:
                self._emit_chunk(
                    chunk_text=sub_text,
                    chunk_type=sub_type,
                    section_path=combined_path,
                    parent_key=parent_key,
                )
            elif sub_type == "article":
                self._process_article(sub_text, combined_path)
            else:
                # Prose blocks trong sub-doc
                if len(sub_text) > self.config.long_prose_threshold and self._has_legal_structure(sub_text):
                    self._parse_appendix_subdoc(sub_text, combined_path)
                elif len(sub_text) > self.config.long_prose_max_chars:
                    self._hierarchical_split_prose(
                        sub_text, "appendix_text", combined_path, parent_key
                    )
                else:
                    self._emit_chunk(
                        chunk_text=sub_text,
                        chunk_type="appendix_text",
                        section_path=combined_path,
                        parent_key=parent_key,
                    )

        # Đổi chunk_type article/clause_group từ sub-doc → appendix_text
        for chunk in self.chunks[start_idx:]:
            if chunk["chunk_type"] in {"article", "clause_group"}:
                chunk["chunk_type"] = "appendix_text"
                chunk["embed"], chunk["keyword_index"] = get_retrieval_flags("appendix_text")
            # Override parent_id về appendix parent
            chunk["parent_id"] = stable_hash(parent_key)

    # --------------------------------------------------------
    # Table summary generation
    # --------------------------------------------------------

    def _generate_table_summary_schema(
        self,
        table_text: str,
        section_path: List[str],
        rows: Optional[List[List[str]]] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rule-based summary schema. Có thể dùng source_table_hash để cache/LLM-enrich sau."""
        rows = rows if rows is not None else self._parse_pipe_rows(table_text)
        path_parts = [p for p in section_path if p not in {"Thân văn bản", "Bảng"}]
        title = " > ".join(path_parts[-3:]) if path_parts else "Bảng trong văn bản"
        columns = self._infer_table_columns(rows)

        entities: List[str] = []
        for row in rows[1:21]:
            for cell in row:
                value = cell.strip()
                if (
                    len(value) >= 5
                    and not re.fullmatch(r"[\d\s.,/%+\-–—]+", value)
                    and value not in entities
                ):
                    entities.append(truncate(value, 120) or value)
                    break
            if len(entities) >= 20:
                break

        joined_columns = " ".join(columns).lower()
        intents = ["tra cứu nội dung trong bảng"]
        for needle, intent in [
            ("phí", "tra cứu mức phí"),
            ("thời hạn", "tra cứu thời hạn giải quyết"),
            ("hồ sơ", "tra cứu thành phần hồ sơ"),
            ("mã", "tra cứu mã hoặc ngạch"),
            ("cơ quan", "tra cứu cơ quan thực hiện"),
        ]:
            if needle in joined_columns:
                intents.append(intent)

        purpose = (
            "Dùng để tìm đúng bảng; giá trị chính xác phải lấy từ raw_table."
            if strategy != "procedure_table"
            else "Dùng để tra cứu danh sách thủ tục; chi tiết lấy từ procedure_record hoặc raw_table."
        )
        return {
            "table_title": title,
            "legal_context": self._legal_context_label(section_path),
            "table_purpose": purpose,
            "main_columns": columns,
            "key_entities": entities,
            "lookup_intents": list(dict.fromkeys(intents)),
            "answer_source": "raw_table",
        }

    def _table_summary_contextual_text(
        self, schema: Dict[str, Any], raw_table_text: str
    ) -> str:
        columns = ", ".join(schema.get("main_columns") or []) or "không xác định rõ"
        entities = "; ".join(schema.get("key_entities") or []) or "không xác định rõ"
        intents = "; ".join(schema.get("lookup_intents") or [])
        lines = [
            f"Bảng này quy định: {schema.get('table_title')}.",
            f"Ngữ cảnh pháp lý: {schema.get('legal_context')}.",
            f"Các cột chính gồm: {columns}.",
            f"Bảng dùng để tra cứu: {intents}.",
            f"Các thực thể chính: {entities}.",
            "Lưu ý: chỉ dùng summary để retrieve; mọi giá trị chính xác phải lấy từ raw_table.",
        ]
        if len(raw_table_text) < self.config.small_table_threshold:
            lines.append(f"Nội dung bảng nhỏ: {raw_table_text}")
        summary = "\n".join(lines)
        return truncate(summary, self.config.table_summary_max_chars) or summary

    def _legal_context_label(self, section_path: List[str]) -> str:
        meta = self.doc_metadata
        doc = " ".join(
            str(meta.get(k) or "").strip()
            for k in ("legal_type", "document_number", "title")
        ).strip()
        path = " > ".join(section_path)
        return " | ".join(x for x in (doc, path) if x) or self.source

    # --------------------------------------------------------
    # Chunk emission
    # --------------------------------------------------------

    def _emit_chunk(
        self,
        chunk_text: str,
        chunk_type: str,
        section_path: List[str],
        parent_key: str,
        section_title: Optional[str] = None,
        procedure_name: Optional[str] = None,
        quality_flags: Optional[List[str]] = None,
        parent_id: Optional[str] = None,
        table_id: Optional[str] = None,
        raw_table_id: Optional[str] = None,
        summary_of: Optional[str] = None,
        source_table_hash: Optional[str] = None,
        table_columns: Optional[List[str]] = None,
        table_summary_schema: Optional[Dict[str, Any]] = None,
        table_strategy: Optional[str] = None,
        answer_source: Optional[str] = None,
        do_not_answer_from_summary: bool = False,
    ) -> Optional[Dict[str, Any]]:
        chunk_text = chunk_text.strip()
        if not chunk_text:
            return None

        flags: List[str] = []
        if quality_flags:
            flags.extend(quality_flags)

        if (
            len(chunk_text) > self.config.hard_max_chars
            and chunk_type not in {"raw_table"}
        ):
            flags.append("oversized_chunk")
        if len(chunk_text) < self.config.min_chars and chunk_type not in {
            "short_text",
            "signature",
            "distribution_list",
            "procedure_record",
            "table_summary",
            "raw_table",
            "table",
            "table_part",
        }:
            flags.append("tiny_chunk")

        contextual_text = self._build_contextual_text(
            chunk_text=chunk_text,
            section_path=section_path,
            section_title=section_title,
            procedure_name=procedure_name,
        )

        chunk_id = make_uuid()
        embed, keyword_index = get_retrieval_flags(chunk_type)
        char_count = len(chunk_text)

        if chunk_type == "procedure_record" and char_count < self.config.tiny_dense_char_limit:
            embed = False
        if chunk_type in {"table", "table_part"} and char_count < self.config.tiny_dense_char_limit:
            embed = False
        if chunk_type == "table_part" and table_strategy == "numeric_or_code_table":
            embed = False
        if "hard_char_split" in flags:
            embed = False
            keyword_index = True
        if (
            char_count > self.config.long_prose_no_embed_threshold
            and chunk_type not in {"raw_table"}
        ):
            embed = False
            keyword_index = True
            flags.append("long_prose_no_embed")

        base: Dict[str, Any] = {
            "chunk_id": chunk_id,
            "doc_id": self.doc_id,
            "source": self.source,

            "chunk_text": chunk_text,
            "contextual_text": contextual_text,

            "chunk_type": chunk_type,
            "section_path": section_path,
            "procedure_name": procedure_name,

            "embed": embed,
            "keyword_index": keyword_index,

            "parent_id": parent_id or stable_hash(parent_key),
            "prev_chunk_id": None,
            "next_chunk_id": None,

            "token_estimate": max(1, int(char_count / 4)),
            "char_count": char_count,

            "table_id": table_id,
            "raw_table_id": raw_table_id,
            "summary_of": summary_of,
            "source_table_hash": source_table_hash,
            "table_columns": table_columns or [],
            "table_summary_schema": table_summary_schema,
            "table_strategy": table_strategy,
            "answer_source": answer_source,
            "do_not_answer_from_summary": do_not_answer_from_summary,

            "quality_flags": sorted(set(flags)),
        }

        self.chunks.append(base)
        return base

    def _build_contextual_text(
        self,
        chunk_text: str,
        section_path: List[str],
        section_title: Optional[str] = None,
        procedure_name: Optional[str] = None,
    ) -> str:
        parts = []
        meta = self.doc_metadata

        legal_type = meta.get("legal_type")
        doc_number = meta.get("document_number")
        title = meta.get("title")

        if legal_type and doc_number and title:
            parts.append(f"Văn bản: {legal_type} {doc_number} - {title}")
        elif legal_type and doc_number:
            parts.append(f"Văn bản: {legal_type} {doc_number}")
        elif title:
            parts.append(f"Văn bản: {title}")
        elif not meta:
            parts.append(f"Văn bản: {self.source}")

        agency = meta.get("issuing_authority")
        if agency:
            parts.append(f"Cơ quan: {agency}")

        issued = meta.get("issuance_date")
        if issued:
            parts.append(f"Ngày ban hành: {issued}")

        effect = meta.get("effect_status")
        if effect:
            parts.append(f"Hiệu lực: {effect}")

        linh_vuc = meta.get("linh_vuc")
        if linh_vuc and len(parts) < 5:
            parts.append(f"Lĩnh vực catalog: {linh_vuc}")

        if section_path and section_path not in [["Thân văn bản"], ["Toàn văn"]]:
            path_str = " > ".join(section_path[-3:]) if len(section_path) > 3 else " > ".join(section_path)
            parts.append(f"Mục: {path_str}")

        if section_title:
            parts.append(f"Tiêu đề: {section_title}")

        if procedure_name:
            parts.append(f"Thủ tục: {procedure_name}")

        prefix = " | ".join(parts) if parts else self.source
        prefix = truncate(prefix, self.config.max_context_prefix_chars) or prefix

        return f"[{prefix}]\n\n{chunk_text}"

    def _make_parent_key(self, section_path: List[str]) -> str:
        return f"{self.doc_id}::{' > '.join(section_path)}"

    @staticmethod
    def _chunk_type_for_split(block_type: str) -> str:
        """Giữ chunk_type gốc khi prose-split; chỉ block không có vai trò rõ → fallback_text."""
        _preserve = {
            "preamble", "legal_basis", "article", "clause_group",
            "appendix", "appendix_group", "appendix_subgroup",
            "part", "chapter", "section", "appendix_text",
        }
        if block_type in _preserve:
            return block_type
        return "fallback_text"

    def _postprocess_chunks(self) -> None:
        """Merge tiny heading/prose vào chunk kế tiếp cùng scope; nếu không thể thì bỏ dense."""
        excluded = {
            "procedure_record", "raw_table", "table_summary", "table", "table_part",
            "signature", "distribution_list", "short_text",
        }
        removed: set = set()
        merged_count = 0
        filtered_count = 0

        for i, chunk in enumerate(self.chunks):
            if i in removed or chunk["char_count"] >= self.config.tiny_dense_char_limit:
                continue
            if chunk["chunk_type"] in excluded:
                continue

            candidate_idx = None
            for j in range(i + 1, len(self.chunks)):
                candidate = self.chunks[j]
                if j in removed or candidate["chunk_type"] in {"signature", "distribution_list"}:
                    continue
                same_scope = (
                    candidate["section_path"] == chunk["section_path"]
                    or candidate["parent_id"] == chunk["parent_id"]
                )
                if same_scope:
                    candidate_idx = j
                break

            if candidate_idx is not None:
                target = self.chunks[candidate_idx]
                target["chunk_text"] = f"{chunk['chunk_text']}\n{target['chunk_text']}".strip()
                target["char_count"] = len(target["chunk_text"])
                target["token_estimate"] = max(1, int(target["char_count"] / 4))
                target["contextual_text"] = self._build_contextual_text(
                    target["chunk_text"],
                    target["section_path"],
                    procedure_name=target.get("procedure_name"),
                )
                if target["chunk_type"] == "raw_table" and target.get("table_id"):
                    new_hash = stable_hash(
                        f"{target['chunk_text']}::{' > '.join(target['section_path'])}",
                        length=40,
                    )
                    for related in self.chunks:
                        if related.get("table_id") == target["table_id"]:
                            related["source_table_hash"] = new_hash
                target["quality_flags"] = sorted(set(
                    target["quality_flags"] + ["tiny_chunk_merged"]
                ))
                removed.add(i)
                merged_count += 1
            else:
                chunk["embed"] = False
                chunk["quality_flags"] = sorted(set(
                    chunk["quality_flags"] + ["tiny_chunk_no_dense"]
                ))
                filtered_count += 1

        if removed:
            self.chunks = [c for idx, c in enumerate(self.chunks) if idx not in removed]
        if self.chunks and (merged_count or filtered_count):
            self.chunks[0]["quality_flags"] = sorted(set(
                self.chunks[0]["quality_flags"]
                + [f"tiny_merged:{merged_count}", f"tiny_dense_filtered:{filtered_count}"]
            ))

    def _finalize_links(self) -> None:
        for i, chunk in enumerate(self.chunks):
            if i > 0:
                chunk["prev_chunk_id"] = self.chunks[i - 1]["chunk_id"]
            if i < len(self.chunks) - 1:
                chunk["next_chunk_id"] = self.chunks[i + 1]["chunk_id"]


# ============================================================
# 8. PUBLIC FUNCTIONS
# ============================================================

def chunk_legal_document(
    doc_id: Any,
    content: str,
    source: str = "unknown",
    doc_metadata: Optional[Dict[str, Any]] = None,
    config: ChunkingConfig = CONFIG,
) -> List[Dict[str, Any]]:
    """
    Entrypoint cho 1 document.
    doc_metadata: một dòng từ metadata.parquet (join theo id), dùng cho contextual_text prefix.
    """
    return VietnameseLegalChunker(
        doc_id=doc_id,
        content=content,
        source=source,
        doc_metadata=doc_metadata,
        config=config,
    ).chunk()


def chunk_legal_documents_from_records(
    records: List[Dict[str, Any]],
    id_col: str = "id",
    content_col: str = "content",
    source_col: str = "source",
    metadata_by_id: Optional[Dict[Any, Dict[str, Any]]] = None,
    config: ChunkingConfig = CONFIG,
) -> List[Dict[str, Any]]:
    """
    Dùng cho list of dict từ content.parquet.
    metadata_by_id: map id → dòng metadata.parquet (xem metadata_lookup_from_dataframe).
    """
    all_chunks = []
    for rec in records:
        doc_id = rec.get(id_col)
        content = rec.get(content_col) or ""
        source = rec.get(source_col) or "unknown"
        meta = (metadata_by_id or {}).get(doc_id)
        chunks = chunk_legal_document(
            doc_id, content, source, doc_metadata=meta, config=config
        )
        all_chunks.extend(chunks)
    return all_chunks


# ============================================================
# 9. OPTIONAL POLARS INTEGRATION
# ============================================================

def chunk_polars_dataframe(
    content_df,
    metadata_df=None,
    id_col: str = "id",
    content_col: str = "content",
    source_col: str = "source",
    metadata_id_col: str = "id",
    config: ChunkingConfig = CONFIG,
):
    """
    Chunk toàn bộ content.parquet; tuỳ chọn join metadata.parquet theo id.

    Example:
        import polars as pl
        content = pl.read_parquet(CONTENT_PATH)
        metadata = pl.read_parquet(METADATA_PATH)
        chunks_df = chunk_polars_dataframe(content, metadata_df=metadata)
        chunks_df.write_parquet("legal_chunks.parquet")
    """
    import polars as pl

    records = content_df.select([id_col, content_col, source_col]).to_dicts()
    meta_by_id = metadata_lookup_from_dataframe(metadata_df, id_col=metadata_id_col) if metadata_df is not None else None
    chunks = chunk_legal_documents_from_records(
        records,
        id_col=id_col,
        content_col=content_col,
        source_col=source_col,
        metadata_by_id=meta_by_id,
        config=config,
    )
    return pl.DataFrame(chunks)
