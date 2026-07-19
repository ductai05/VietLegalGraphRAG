import asyncio
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vietlegal_rag.pipe import _extract_ocr_text  # noqa: E402

_ALLOWED = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
)


class _FakeOcr:
    def __init__(self, text: str = "OCR TEXT", raises: bool = False) -> None:
        self.text = text
        self.raises = raises
        self.calls: list[tuple[bytes, str]] = []

    def process(self, content: bytes, mime_type: str) -> dict:
        self.calls.append((content, mime_type))
        if self.raises:
            raise RuntimeError("vision down")
        return {"success": True, "text": self.text, "pages": [], "mime_type": mime_type}


def _img_data_url(mime: str = "image/png", raw: bytes = b"\x89PNG_fake") -> str:
    b64 = base64.b64encode(raw).decode()
    return f"data:{mime};base64,{b64}"


def _body_with_image(mime: str = "image/png") -> dict:
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Đây là gì?"},
                    {"type": "image_url", "image_url": {"url": _img_data_url(mime)}},
                ],
            }
        ]
    }


def _run(coro):
    return asyncio.run(coro)


def test_inline_image_is_ocred_and_returned():
    ocr = _FakeOcr("Giấy chứng nhận quyền sử dụng đất")
    out = _run(
        _extract_ocr_text(
            _body_with_image(), ocr, allowed_mimes=_ALLOWED, max_file_bytes=10 * 1024 * 1024
        )
    )
    assert "Giấy chứng nhận quyền sử dụng đất" in out
    assert ocr.calls and ocr.calls[0][1] == "image/png"


def test_disallowed_mime_is_skipped():
    ocr = _FakeOcr()
    out = _run(
        _extract_ocr_text(
            _body_with_image("image/tiff"), ocr, allowed_mimes=_ALLOWED, max_file_bytes=10 * 1024 * 1024
        )
    )
    assert out == ""
    assert ocr.calls == []


def test_oversize_image_is_skipped():
    ocr = _FakeOcr()
    out = _run(
        _extract_ocr_text(
            _body_with_image(), ocr, allowed_mimes=_ALLOWED, max_file_bytes=1
        )
    )
    assert out == ""
    assert ocr.calls == []


def test_ocr_failure_yields_empty_string():
    ocr = _FakeOcr(raises=True)
    out = _run(
        _extract_ocr_text(
            _body_with_image(), ocr, allowed_mimes=_ALLOWED, max_file_bytes=10 * 1024 * 1024
        )
    )
    assert out == ""


def test_no_attachments_yields_empty_string():
    ocr = _FakeOcr()
    body = {"messages": [{"role": "user", "content": "Chỉ có chữ"}]}
    out = _run(
        _extract_ocr_text(body, ocr, allowed_mimes=_ALLOWED, max_file_bytes=10 * 1024 * 1024)
    )
    assert out == ""
    assert ocr.calls == []


def _body_with_file_ids(*ids: str) -> dict:
    return {
        "messages": [{"role": "user", "content": "Xem tài liệu đính kèm"}],
        "metadata": {"files": [{"type": "file", "id": i} for i in ids]},
    }


def _loader(mapping):
    async def _load(file_id):
        return mapping.get(file_id)  # (bytes, mime, extracted_text) or None
    return _load


def test_scanned_pdf_with_empty_owui_text_is_ocred():
    ocr = _FakeOcr("Điều 1. Phạm vi điều chỉnh")
    loader = _loader({"f1": (b"%PDF-fake", "application/pdf", "   ")})
    out = _run(
        _extract_ocr_text(
            _body_with_file_ids("f1"), ocr, loader,
            allowed_mimes=_ALLOWED, max_file_bytes=10 * 1024 * 1024,
        )
    )
    assert "Phạm vi điều chỉnh" in out
    assert ocr.calls and ocr.calls[0][1] == "application/pdf"


def test_pdf_with_existing_owui_text_skips_ocr():
    ocr = _FakeOcr()
    loader = _loader({"f1": (b"%PDF", "application/pdf", "Đã có nội dung trích")})
    out = _run(
        _extract_ocr_text(
            _body_with_file_ids("f1"), ocr, loader,
            allowed_mimes=_ALLOWED, max_file_bytes=10 * 1024 * 1024,
        )
    )
    assert out == ""
    assert ocr.calls == []


def test_missing_file_is_skipped():
    ocr = _FakeOcr()
    loader = _loader({})  # loader returns None
    out = _run(
        _extract_ocr_text(
            _body_with_file_ids("nope"), ocr, loader,
            allowed_mimes=_ALLOWED, max_file_bytes=10 * 1024 * 1024,
        )
    )
    assert out == ""
    assert ocr.calls == []
