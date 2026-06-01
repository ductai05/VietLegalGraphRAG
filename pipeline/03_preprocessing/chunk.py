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
    emit_parent_chunks: bool = False


CONFIG = ChunkingConfig()


# ============================================================
# 2. REGEX HELPERS
# ============================================================

RE_WHITESPACE = re.compile(r"[ \t]+")
RE_MULTI_NEWLINE = re.compile(r"\n{3,}")

RE_DOC_NUMBER = re.compile(
    r"(?im)\b(?:Số|Số hiệu|Quyết định số|Nghị định số|Thông tư số|Nghị quyết số|Công văn số)"
    r"\s*[:\-]?\s*([0-9]{1,4}(?:/[0-9]{4})?/[A-ZĐ0-9\-.]+|[0-9]{1,6}/[A-ZĐ0-9\-.]+|[0-9]{1,6})"
)

RE_DATE_VN = re.compile(
    r"(?i)\bngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})\b"
)

RE_DOC_TYPE = re.compile(
    r"(?im)^\s*(QUYẾT ĐỊNH|NGHỊ ĐỊNH|THÔNG TƯ|NGHỊ QUYẾT|CÔNG VĂN|CHỈ THỊ|LUẬT|BỘ LUẬT|KẾ HOẠCH|QUY CHẾ|THÔNG BÁO)\b"
)

RE_TITLE_HINT = re.compile(r"(?im)\b(?:V/v|Về việc|Về)\s*[:\-]?\s*(.+)$")

RE_AGENCY_LINE = re.compile(
    r"(?im)^\s*((?:ỦY BAN NHÂN DÂN|HỘI ĐỒNG NHÂN DÂN|CHÍNH PHỦ|THỦ TƯỚNG CHÍNH PHỦ|"
    r"BỘ\s+[A-ZÀ-Ỵ\s]+|TỔNG CỤC\s+[A-ZÀ-Ỵ\s]+|CỤC\s+[A-ZÀ-Ỵ\s]+|"
    r"SỞ\s+[A-ZÀ-Ỵ\s]+|TÒA ÁN NHÂN DÂN|VIỆN KIỂM SÁT NHÂN DÂN)"
    r"(?:\s+[A-ZÀ-Ỵ\s]+)?)\s*$"
)

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
RE_POINT = re.compile(r"^\s*([a-zđ])\)\s+", re.IGNORECASE)

RE_FOOTER = re.compile(r"(?im)^\s*(Nơi nhận\s*[:\-].*)$", re.DOTALL)

RE_LEGAL_REFS = [
    re.compile(r"\b(?:Luật|Bộ luật|Nghị định|Thông tư|Quyết định|Nghị quyết|Công văn|Chỉ thị)\s+(?:số\s+)?\d+(?:/\d+)?/[A-ZĐ0-9\-.]+", re.IGNORECASE),
    re.compile(r"\b(?:Luật|Bộ luật)\s+[A-ZÀ-Ỵa-zà-ỹ\s,]+?\s+năm\s+\d{4}", re.IGNORECASE),
    re.compile(r"\b(?:Điều|Khoản|Điểm)\s+\d+[a-zA-Z]?\b", re.IGNORECASE),
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
        text = re.sub(r"\s*\|\s*", " | ", text)
        text = re.sub(r"[ \t]{2,}", " ", text)

        text = LegalTextNormalizer._explode_flattened_pipe_tables(text)

        return text.strip()

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
                    r"\s+(?=(?:PHỤ\s+LỤC|I\.|II\.|III\.|IV\.|V\.|VI\.|VII\.|VIII\.|IX\.|X\.)\s+[A-ZÀ-Ỵ])",
                    "\n",
                    s
                )
                new_lines.extend([x.strip() for x in s.split("\n") if x.strip()])
            else:
                new_lines.append(line)
        return "\n".join(new_lines)


# ============================================================
# 4. METADATA EXTRACTOR
# ============================================================

class MetadataExtractor:
    @staticmethod
    def extract(text: str, source: str = "unknown") -> Dict[str, Any]:
        header = "\n".join(text.split("\n")[:40])

        metadata: Dict[str, Any] = {
            "doc_number": None,
            "issued_date": None,
            "agency": None,
            "doc_type": None,
            "title": None,
            "source": source,
            "quality_flags": [],
        }

        num_match = RE_DOC_NUMBER.search(header)
        if num_match:
            metadata["doc_number"] = num_match.group(1).strip()

        date_match = RE_DATE_VN.search(header)
        if date_match:
            d, m, y = date_match.groups()
            metadata["issued_date"] = f"{d.zfill(2)}/{m.zfill(2)}/{y}"

        type_match = RE_DOC_TYPE.search(header)
        if type_match:
            metadata["doc_type"] = type_match.group(1).strip().upper()

        agency = MetadataExtractor._extract_agency(header)
        if agency:
            metadata["agency"] = agency

        title = MetadataExtractor._extract_title(header, metadata["doc_type"])
        if title:
            metadata["title"] = title

        if not metadata["doc_number"]:
            metadata["quality_flags"].append("missing_doc_number")
        if not metadata["doc_type"]:
            metadata["quality_flags"].append("missing_doc_type")
        if not metadata["agency"]:
            metadata["quality_flags"].append("missing_agency")
        if not metadata["title"]:
            metadata["quality_flags"].append("missing_title")

        return metadata

    @staticmethod
    def _extract_agency(header: str) -> Optional[str]:
        ignore = {
            "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
            "ĐỘC LẬP - TỰ DO - HẠNH PHÚC",
            "Độc lập - Tự do - Hạnh phúc",
        }

        for line in header.split("\n")[:25]:
            clean = line.strip(" |")
            if not clean or clean.upper() in {x.upper() for x in ignore}:
                continue

            left = clean.split("|")[0].strip()
            m = RE_AGENCY_LINE.match(left)
            if m:
                return m.group(1).strip()

            m = RE_AGENCY_LINE.match(clean)
            if m:
                return m.group(1).strip()

        return None

    @staticmethod
    def _extract_title(header: str, doc_type: Optional[str]) -> Optional[str]:
        title_match = RE_TITLE_HINT.search(header)
        if title_match:
            title = title_match.group(1).strip()
            return MetadataExtractor._clean_title(title)

        lines = [x.strip(" |") for x in header.split("\n") if x.strip(" |")]
        for i, line in enumerate(lines[:20]):
            if doc_type and doc_type in line.upper():
                candidates = []
                for nxt in lines[i + 1:i + 5]:
                    upper = nxt.upper()
                    if upper.startswith("CĂN CỨ"):
                        break
                    if "SỐ:" in upper or "NGÀY" in upper:
                        continue
                    if len(nxt) >= 12:
                        candidates.append(nxt)
                if candidates:
                    return MetadataExtractor._clean_title(" ".join(candidates))

        return None

    @staticmethod
    def _clean_title(title: str) -> str:
        title = re.sub(r"\s+", " ", title).strip(" .;-")
        if len(title) > 350:
            title = title[:347] + "..."
        return title


# ============================================================
# 5. REFERENCE EXTRACTOR
# ============================================================

class ReferenceExtractor:
    @staticmethod
    def extract(text: str) -> List[str]:
        refs = []
        for pat in RE_LEGAL_REFS:
            refs.extend([m.group(0).strip() for m in pat.finditer(text)])

        seen: set = set()
        out = []
        for r in refs:
            key = r.lower()
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out[:50]


# ============================================================
# 6. UTILS
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


def is_probably_table_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s.count("|") >= 2:
        return True
    if re.search(r"\bSỐ\s*TT\b", s, re.IGNORECASE) and re.search(r"\bTHỦ\s*TỤC\b", s, re.IGNORECASE):
        return True
    return False


def split_sentences_vi(text: str) -> List[str]:
    protected = {
        "TP.": "TP<dot>",
        "UBND.": "UBND<dot>",
        "HĐND.": "HDND<dot>",
        "P.": "P<dot>",
        "Q.": "Q<dot>",
    }
    s = text
    for k, v in protected.items():
        s = s.replace(k, v)

    parts = re.split(r"(?<=[.!?;:])\s+(?=[A-ZÀ-Ỵ0-9Đ])", s)
    out = []
    for p in parts:
        for k, v in protected.items():
            p = p.replace(v, k)
        p = p.strip()
        if p:
            out.append(p)
    return out


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


# ============================================================
# 8. MAIN CHUNKER
# ============================================================

class VietnameseLegalChunker:
    def __init__(
        self,
        doc_id: Any,
        content: str,
        source: str = "unknown",
        config: ChunkingConfig = CONFIG,
    ):
        self.doc_id = str(doc_id)
        self.raw_content = content or ""
        self.source = source
        self.config = config

        self.normalized_text = LegalTextNormalizer.normalize(self.raw_content)
        self.doc_metadata = MetadataExtractor.extract(self.normalized_text, source=source)

        self.chunks: List[Dict[str, Any]] = []
        self.parent_store: Dict[str, Dict[str, Any]] = {}

    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def chunk(self) -> List[Dict[str, Any]]:
        text = self.normalized_text.strip()
        if not text:
            return []

        if len(text) < self.config.short_doc_threshold:
            self._emit_chunk(
                chunk_text=text,
                chunk_type="short_text",
                chunk_level="document",
                section_path=["Toàn văn"],
                section="Toàn văn",
                section_title=None,
                appendix=None,
                subfield=None,
                quality_flags=["short_document"],
                parent_key=self._make_parent_key(["Toàn văn"]),
            )
            self._finalize_links()
            return self.chunks

        body_text, footer_blocks = self._extract_footer(text)
        blocks = self._split_into_blocks(body_text)

        for block in blocks:
            self._process_block(block)

        for block in footer_blocks:
            self._process_block(block)

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

        blocks = []

        sig_patterns = [
            r"\bKT\.\s+",
            r"\bTM\.\s+",
            r"\bCHỦ\s+TỊCH\b",
            r"\bPHÓ\s+CHỦ\s+TỊCH\b",
            r"\bBỘ\s+TRƯỞNG\b",
            r"\bTHỨ\s+TRƯỞNG\b",
            r"\bGIÁM\s+ĐỐC\b",
        ]

        sig_pos = None
        for pat in sig_patterns:
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

        def current_appendix_id() -> Optional[str]:
            if state.get("appendix"):
                return state["appendix"]["id"]
            return None

        def current_subfield_id() -> Optional[str]:
            if state.get("sub_field"):
                return state["sub_field"]["id"]
            if state.get("major_field"):
                return state["major_field"]["id"]
            return None

        def flush_current():
            nonlocal current_lines, current_type, current_level, current_path
            txt = "\n".join(current_lines).strip()
            if txt:
                blocks.append(self._make_block(
                    txt, current_type, current_level, current_path,
                    appendix=current_appendix_id(),
                    subfield=current_subfield_id(),
                ))
            current_lines = []

        def flush_table():
            nonlocal table_lines, in_table
            txt = "\n".join(table_lines).strip()
            if txt:
                blocks.append(self._make_block(
                    txt, "table", "table", current_section_path(),
                    appendix=current_appendix_id(),
                    subfield=current_subfield_id(),
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

            if is_probably_table_line(line):
                if not in_table:
                    flush_current()
                    table_lines = []
                    in_table = True
                table_lines.append(line)
                continue

            if in_table:
                flush_table()

            heading = self._parse_heading(line)
            if heading:
                flush_current()

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
                    current_type, current_level = "appendix", "appendix"

                elif h_type == "part":
                    state.update({
                        "part": {"id": h_id, "title": h_title},
                        "chapter": None,
                        "section": None,
                        "article": None,
                    })
                    current_type, current_level = "part", "part"

                elif h_type == "chapter":
                    state.update({
                        "chapter": {"id": h_id, "title": h_title},
                        "section": None,
                        "article": None,
                    })
                    current_type, current_level = "chapter", "chapter"

                elif h_type == "section":
                    state.update({
                        "section": {"id": h_id, "title": h_title},
                        "article": None,
                    })
                    current_type, current_level = "section", "section"

                elif h_type == "article":
                    state.update({
                        "article": {"id": h_id, "title": h_title},
                    })
                    current_type, current_level = "article", "article"

                current_path = current_section_path()
                current_lines.append(line)
                continue

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

    def _parse_heading(self, line: str) -> Optional[Dict[str, str]]:
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

        m = RE_ARTICLE.match(line)
        if m:
            number = m.group(2)
            title = m.group(3) or None
            return {
                "type": "article",
                "id": f"Điều {number}",
                "title": truncate(title, self.config.max_section_title_chars),
            }

        return None

    def _parse_appendix_group_heading(self, line: str) -> Optional[Dict[str, str]]:
        s = line.strip(" |")

        m = re.match(r"^([IVXLCDM]{1,6})\.\s+(.{3,})$", s, re.IGNORECASE)
        if m and len(s) <= 180:
            title = m.group(2).strip()
            if title.upper() == title or "TTHC" in title.upper() or "LĨNH VỰC" in title.upper():
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
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "text": text.strip(),
            "type": typ,
            "level": level,
            "section_path": section_path or ["Thân văn bản"],
            "appendix": appendix,
            "subfield": subfield,
        }

    # --------------------------------------------------------
    # Block processing
    # --------------------------------------------------------

    def _process_block(self, block: Dict[str, Any]) -> None:
        text = block["text"].strip()
        if not text:
            return

        typ = block["type"]
        level = block["level"]
        section_path = block["section_path"]
        appendix = block.get("appendix")
        subfield = block.get("subfield")

        if typ == "table":
            self._process_table(text, section_path, appendix=appendix, subfield=subfield)
            return

        if typ == "article":
            self._process_article(text, section_path, appendix=appendix, subfield=subfield)
            return

        if typ in {"distribution_list", "signature"}:
            self._emit_chunk(
                chunk_text=text,
                chunk_type=typ,
                chunk_level=level,
                section_path=section_path,
                section=section_path[-1],
                section_title=None,
                appendix=appendix,
                subfield=subfield,
                parent_key=self._make_parent_key(section_path),
            )
            return

        if len(text) <= self.config.max_chars:
            self._emit_chunk(
                chunk_text=text,
                chunk_type=typ,
                chunk_level=level,
                section_path=section_path,
                section=section_path[-1],
                section_title=None,
                appendix=appendix,
                subfield=subfield,
                parent_key=self._make_parent_key(section_path),
            )
        else:
            self._split_prose(
                text=text,
                chunk_type=typ,
                chunk_level=level,
                section_path=section_path,
                appendix=appendix,
                subfield=subfield,
                parent_key=self._make_parent_key(section_path),
            )

    # --------------------------------------------------------
    # Article processing
    # --------------------------------------------------------

    def _process_article(
        self,
        text: str,
        section_path: List[str],
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
    ) -> None:
        article_id, article_title = self._extract_article_id_title(text)
        parent_key = self._make_parent_key(section_path)

        self._register_parent(parent_key, text, section_path, "article_parent")

        if len(text) <= self.config.max_chars:
            self._emit_chunk(
                chunk_text=text,
                chunk_type="article",
                chunk_level="article",
                section_path=section_path,
                section=article_id or section_path[-1],
                section_title=article_title,
                appendix=appendix,
                subfield=subfield,
                parent_key=parent_key,
            )
            return

        title_line, clauses = self._split_article_into_clauses(text)
        if not clauses:
            self._split_prose(
                text=text,
                chunk_type="article",
                chunk_level="article",
                section_path=section_path,
                appendix=appendix,
                subfield=subfield,
                parent_key=parent_key,
                section=article_id,
                section_title=article_title,
            )
            return

        current = []
        current_len = len(title_line)

        for clause in clauses:
            if current and current_len + len(clause) > self.config.max_chars:
                chunk_text = title_line + "\n" + "\n".join(current)
                self._emit_chunk(
                    chunk_text=chunk_text,
                    chunk_type="clause_group",
                    chunk_level="clause",
                    section_path=section_path,
                    section=article_id,
                    section_title=article_title,
                    appendix=appendix,
                    subfield=subfield,
                    parent_key=parent_key,
                )
                overlap = smart_overlap("\n".join(current), self.config.overlap_chars)
                current = [overlap, clause] if overlap else [clause]
                current_len = len(title_line) + sum(len(x) for x in current)
            else:
                current.append(clause)
                current_len += len(clause) + 1

        if current:
            chunk_text = title_line + "\n" + "\n".join(current)
            self._emit_chunk(
                chunk_text=chunk_text,
                chunk_type="clause_group",
                chunk_level="clause",
                section_path=section_path,
                section=article_id,
                section_title=article_title,
                appendix=appendix,
                subfield=subfield,
                parent_key=parent_key,
            )

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
            if RE_CLAUSE.match(line.strip()) and current:
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

    def _process_table(
        self,
        table_text: str,
        section_path: List[str],
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
    ) -> None:
        parent_key = self._make_parent_key(section_path + ["Bảng"])
        self._register_parent(parent_key, table_text, section_path, "table_parent")

        if self.config.parse_procedure_tables and self._looks_like_procedure_table(table_text):
            records = self._parse_procedure_table_records(table_text, section_path, parent_key)
            if records:
                for rec in records:
                    self._emit_procedure_record(
                        rec, section_path, parent_key,
                        appendix=appendix, subfield=subfield,
                    )
                return

        rows = self._parse_pipe_rows(table_text)

        # ≤ table_max_chars (2000) → giữ nguyên Markdown; > table_row_mode_threshold (2500) → split rows
        if len(table_text) <= self.config.table_max_chars or len(rows) <= 4:
            self._emit_chunk(
                chunk_text=table_text,
                chunk_type="table",
                chunk_level="table",
                section_path=section_path,
                section=section_path[-1],
                section_title=None,
                appendix=appendix,
                subfield=subfield,
                parent_key=parent_key,
            )
            return

        self._split_large_table_rows(
            rows, section_path, parent_key,
            appendix=appendix, subfield=subfield,
        )

    def _looks_like_procedure_table(self, text: str) -> bool:
        lower = text.lower()
        if "thủ tục hành chính" in lower or "tên thủ tục" in lower or "tthc" in lower:
            return True

        rows = self._parse_pipe_rows(text)
        numeric_rows = 0
        for cells in rows:
            cells2 = [c for c in cells if c.strip()]
            if len(cells2) >= 2 and re.match(r"^\d{1,4}$", cells2[0].strip()):
                numeric_rows += 1
        return numeric_rows >= 3

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
            if "thủ tục" in joined or "tên thủ tục" in joined or "số tt" in joined:
                return row
        return []

    def _is_header_like(self, cells: List[str]) -> bool:
        joined = " ".join(cells).lower()
        if not joined:
            return True
        if "tên thủ tục" in joined or "số tt" in joined or "ghi chú" in joined:
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
            if candidate.upper() == candidate or "TTHC" in candidate.upper():
                return truncate(candidate, 180)

        m = re.match(r"^([IVXLCDM]{1,6})\.\s+(.+)$", joined, re.IGNORECASE)
        if m:
            candidate = m.group(2).strip()
            if candidate.upper() == candidate or "TTHC" in candidate.upper():
                return truncate(candidate, 180)

        return None

    def _detect_sub_field_row(self, cells: List[str]) -> Optional[str]:
        joined = " ".join([c for c in cells if c.strip()])
        m = re.search(r"(Lĩnh vực\s*[:\-]?\s*.+)$", joined, re.IGNORECASE)
        if m and len(joined) <= 250:
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
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
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

        effective_subfield = subfield or rec.get("sub_field") or rec.get("major_field")

        self._emit_chunk(
            chunk_text=chunk_text,
            chunk_type="procedure_record",
            chunk_level="row",
            section_path=record_path,
            section=f"procedure_{rec.get('stt')}",
            section_title=rec.get("procedure_name"),
            appendix=appendix,
            subfield=effective_subfield,
            parent_key=parent_key,
            procedure_name=rec.get("procedure_name"),
            field=rec.get("sub_field") or rec.get("major_field"),
            extra_metadata={
                "procedure_stt": rec.get("stt"),
                "receive_by_post": rec.get("receive_by_post"),
                "return_by_post": rec.get("return_by_post"),
                "raw_table_cells": rec.get("raw_cells"),
            },
        )

    def _split_large_table_rows(
        self,
        rows: List[List[str]],
        section_path: List[str],
        parent_key: str,
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
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
                    chunk_level="table",
                    section_path=section_path,
                    section=section_path[-1],
                    section_title=None,
                    appendix=appendix,
                    subfield=subfield,
                    parent_key=parent_key,
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
                chunk_level="table",
                section_path=section_path,
                section=section_path[-1],
                section_title=None,
                appendix=appendix,
                subfield=subfield,
                parent_key=parent_key,
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
        chunk_level: str,
        section_path: List[str],
        parent_key: str,
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
        section: Optional[str] = None,
        section_title: Optional[str] = None,
    ) -> None:
        sentences = split_sentences_vi(text)

        if len(sentences) <= 1:
            self._split_by_hard_chars(
                text=text,
                chunk_type=chunk_type,
                chunk_level=chunk_level,
                section_path=section_path,
                parent_key=parent_key,
                appendix=appendix,
                subfield=subfield,
                section=section,
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
                    chunk_level=chunk_level,
                    section_path=section_path,
                    section=section or section_path[-1],
                    section_title=section_title,
                    appendix=appendix,
                    subfield=subfield,
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
                chunk_level=chunk_level,
                section_path=section_path,
                section=section or section_path[-1],
                section_title=section_title,
                appendix=appendix,
                subfield=subfield,
                parent_key=parent_key,
            )

    def _split_by_hard_chars(
        self,
        text: str,
        chunk_type: str,
        chunk_level: str,
        section_path: List[str],
        parent_key: str,
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
        section: Optional[str] = None,
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
                    chunk_level=chunk_level,
                    section_path=section_path,
                    section=section or section_path[-1],
                    section_title=section_title,
                    appendix=appendix,
                    subfield=subfield,
                    parent_key=parent_key,
                    quality_flags=["hard_char_split"],
                )
            start += step

    # --------------------------------------------------------
    # Chunk emission
    # --------------------------------------------------------

    def _emit_chunk(
        self,
        chunk_text: str,
        chunk_type: str,
        chunk_level: str,
        section_path: List[str],
        section: Optional[str],
        section_title: Optional[str],
        parent_key: str,
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
        procedure_name: Optional[str] = None,
        field: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        quality_flags: Optional[List[str]] = None,
    ) -> None:
        chunk_text = chunk_text.strip()
        if not chunk_text:
            return

        flags = list(self.doc_metadata.get("quality_flags", []))
        if quality_flags:
            flags.extend(quality_flags)

        if len(chunk_text) > self.config.hard_max_chars:
            flags.append("oversized_chunk")
        if len(chunk_text) < self.config.min_chars and chunk_type not in {
            "short_text",
            "signature",
            "distribution_list",
            "procedure_record",
        }:
            flags.append("tiny_chunk")

        contextual_text = self._build_contextual_text(
            chunk_text=chunk_text,
            section_path=section_path,
            section=section,
            section_title=section_title,
            appendix=appendix,
            subfield=subfield,
            procedure_name=procedure_name,
            field=field,
        )

        chunk_id = make_uuid()

        base: Dict[str, Any] = {
            "chunk_id": chunk_id,
            "doc_id": self.doc_id,
            "source": self.source,

            "chunk_text": chunk_text,
            "contextual_text": contextual_text,

            "chunk_type": chunk_type,
            "chunk_level": chunk_level,

            "title": self.doc_metadata.get("title"),
            "doc_type": self.doc_metadata.get("doc_type"),
            "agency": self.doc_metadata.get("agency"),
            "doc_number": self.doc_metadata.get("doc_number"),
            "issued_date": self.doc_metadata.get("issued_date"),

            "section_path": section_path,
            "section": section,

            "appendix": appendix,
            "field": field,
            "subfield": subfield,
            "procedure_name": procedure_name,

            "legal_references": ReferenceExtractor.extract(chunk_text),

            "parent_id": stable_hash(parent_key),
            "prev_chunk_id": None,
            "next_chunk_id": None,

            "token_estimate": max(1, int(len(chunk_text) / 4)),

            "quality_flags": sorted(set(flags)),
        }

        if extra_metadata:
            base.update(extra_metadata)

        self.chunks.append(base)

    def _build_contextual_text(
        self,
        chunk_text: str,
        section_path: List[str],
        section: Optional[str],
        section_title: Optional[str],
        appendix: Optional[str] = None,
        subfield: Optional[str] = None,
        procedure_name: Optional[str] = None,
        field: Optional[str] = None,
    ) -> str:
        parts = []

        doc_label = self.doc_metadata.get("doc_type") or "Văn bản"
        doc_number = self.doc_metadata.get("doc_number")
        title = self.doc_metadata.get("title")

        if doc_number and title:
            parts.append(f"Văn bản: {doc_label} {doc_number} - {title}")
        elif doc_number:
            parts.append(f"Văn bản: {doc_label} {doc_number}")
        elif title:
            parts.append(f"Văn bản: {title}")
        else:
            parts.append(f"Văn bản: {self.source}")

        agency = self.doc_metadata.get("agency")
        if agency:
            parts.append(f"Cơ quan: {agency}")

        issued = self.doc_metadata.get("issued_date")
        if issued:
            parts.append(f"Ngày: {issued}")

        if appendix:
            parts.append(f"Phụ lục: {appendix}")

        effective_field = field or subfield
        if effective_field:
            parts.append(f"Lĩnh vực: {effective_field}")

        if section_path and section_path not in [["Thân văn bản"], ["Toàn văn"]]:
            path_str = " > ".join(section_path[-3:]) if len(section_path) > 3 else " > ".join(section_path)
            parts.append(f"Mục: {path_str}")
        elif section:
            parts.append(f"Mục: {section}")

        if section_title:
            parts.append(f"Tiêu đề: {section_title}")

        if procedure_name:
            parts.append(f"Thủ tục: {procedure_name}")

        prefix = " | ".join(parts)
        prefix = truncate(prefix, self.config.max_context_prefix_chars) or prefix

        return f"[{prefix}]\n\n{chunk_text}"

    def _make_parent_key(self, section_path: List[str]) -> str:
        return f"{self.doc_id}::{' > '.join(section_path)}"

    def _register_parent(
        self,
        parent_key: str,
        parent_text: str,
        section_path: List[str],
        parent_type: str,
    ) -> None:
        parent_id = stable_hash(parent_key)
        if parent_key not in self.parent_store:
            self.parent_store[parent_key] = {
                "parent_id": parent_id,
                "parent_key": parent_key,
                "doc_id": self.doc_id,
                "parent_type": parent_type,
                "section_path": section_path,
                "parent_text": parent_text,
                "char_len": len(parent_text),
            }

        if self.config.emit_parent_chunks:
            self._emit_chunk(
                chunk_text=parent_text,
                chunk_type=parent_type,
                chunk_level="parent",
                section_path=section_path,
                section=section_path[-1] if section_path else "parent",
                section_title=None,
                appendix=None,
                subfield=None,
                parent_key=parent_key,
                quality_flags=["parent_context_chunk"],
            )

    def _finalize_links(self) -> None:
        for i, chunk in enumerate(self.chunks):
            if i > 0:
                chunk["prev_chunk_id"] = self.chunks[i - 1]["chunk_id"]
            if i < len(self.chunks) - 1:
                chunk["next_chunk_id"] = self.chunks[i + 1]["chunk_id"]


# ============================================================
# 9. PUBLIC FUNCTIONS
# ============================================================

def chunk_legal_document(
    doc_id: Any,
    content: str,
    source: str = "unknown",
    config: ChunkingConfig = CONFIG,
) -> List[Dict[str, Any]]:
    """
    Main entrypoint cho 1 document.
    Return: list[dict], mỗi dict là 1 chunk sẵn sàng ghi parquet/jsonl/vector DB.
    """
    return VietnameseLegalChunker(
        doc_id=doc_id,
        content=content,
        source=source,
        config=config,
    ).chunk()


def chunk_legal_documents_from_records(
    records: List[Dict[str, Any]],
    id_col: str = "id",
    content_col: str = "content",
    source_col: str = "source",
    config: ChunkingConfig = CONFIG,
) -> List[Dict[str, Any]]:
    """
    Dùng cho list of dict:
    [
        {"id": 1, "content": "...", "source": "legacy"},
        ...
    ]
    """
    all_chunks = []
    for rec in records:
        doc_id = rec.get(id_col)
        content = rec.get(content_col) or ""
        source = rec.get(source_col) or "unknown"
        chunks = chunk_legal_document(doc_id, content, source, config=config)
        all_chunks.extend(chunks)
    return all_chunks


# ============================================================
# 10. OPTIONAL POLARS INTEGRATION
# ============================================================

def chunk_polars_dataframe(
    df,
    id_col: str = "id",
    content_col: str = "content",
    source_col: str = "source",
    config: ChunkingConfig = CONFIG,
):
    """
    Optional: dùng nếu bạn đang đọc parquet bằng Polars.

    Example:
        import polars as pl
        content = pl.read_parquet(CONTENT_PATH)
        chunks_df = chunk_polars_dataframe(content)
        chunks_df.write_parquet("legal_chunks.parquet")
    """
    import polars as pl

    records = df.select([id_col, content_col, source_col]).to_dicts()
    chunks = chunk_legal_documents_from_records(
        records,
        id_col=id_col,
        content_col=content_col,
        source_col=source_col,
        config=config,
    )
    return pl.DataFrame(chunks)
