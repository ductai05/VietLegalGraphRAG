from contract_ocr.models import OCRDocument, OCRLine, OCRPage


def _document() -> OCRDocument:
    return OCRDocument(
        filename="contract.pdf",
        total_pages=3,
        processed_pages=2,
        truncated=True,
        detector_model="det",
        recognizer_model="rec",
        device="gpu:0",
        elapsed_seconds=1.234,
        pages=[
            OCRPage(
                page_number=1,
                width=100,
                height=200,
                lines=[
                    OCRLine("Điều 1", 0.9, [[1, 2], [3, 4]]),
                    OCRLine("   ", 0.1),
                ],
            ),
            OCRPage(
                page_number=2,
                width=100,
                height=200,
                lines=[OCRLine("Thanh toán", 0.8)],
            ),
        ],
    )


def test_page_and_document_text_keep_page_boundaries() -> None:
    document = _document()

    assert document.pages[0].text == "Điều 1"
    assert document.text == (
        "=== Trang 1 ===\nĐiều 1\n\n"
        "=== Trang 2 ===\nThanh toán"
    )


def test_document_metrics_serialization_and_table_rows() -> None:
    document = _document()

    assert document.line_count == 3
    assert document.average_confidence == 0.6
    assert document.table_rows() == [
        [1, 1, "Điều 1", 0.9],
        [1, 2, "   ", 0.1],
        [2, 1, "Thanh toán", 0.8],
    ]

    serialized = document.to_dict()
    assert serialized["line_count"] == 3
    assert serialized["average_confidence"] == 0.6
    assert serialized["pages"][0]["lines"][0]["polygon"] == [[1, 2], [3, 4]]


def test_empty_document_has_zero_confidence() -> None:
    document = OCRDocument(
        filename="empty.pdf",
        total_pages=1,
        processed_pages=1,
        truncated=False,
        detector_model="det",
        recognizer_model="rec",
        device="cpu",
        elapsed_seconds=0,
    )

    assert document.line_count == 0
    assert document.average_confidence == 0.0
    assert document.text == ""
