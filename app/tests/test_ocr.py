from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from contract_ocr.config import Settings
from contract_ocr.exceptions import OCRProcessingError
from contract_ocr.ocr import (
    PaddleOCREngine,
    _polygon_to_list,
    _polygon_to_horizontal_box,
    _sort_lines,
    _sort_polygons,
    _to_list,
    _to_plain_mapping,
)


def test_result_mapping_supports_mapping_json_and_nested_res() -> None:
    assert _to_plain_mapping({"rec_texts": ["A"]}) == {"rec_texts": ["A"]}
    assert _to_plain_mapping({"res": {"rec_texts": ["B"]}}) == {
        "rec_texts": ["B"]
    }

    json_result = SimpleNamespace(
        json=lambda: '{"res": {"rec_texts": ["C"]}}'
    )
    assert _to_plain_mapping(json_result) == {"rec_texts": ["C"]}

    invalid_json_with_res = SimpleNamespace(
        json="{not-json}",
        res={"rec_texts": ["D"]},
    )
    assert _to_plain_mapping(invalid_json_with_res) == {"rec_texts": ["D"]}
    assert _to_plain_mapping(object()) == {}


def test_list_and_polygon_helpers_cover_empty_and_numpy_values() -> None:
    assert _to_list(None) == []
    assert _to_list(np.array([1, 2])) == [1, 2]
    assert _to_list(("a", "b")) == ["a", "b"]
    assert _polygon_to_list(None) == []
    assert _polygon_to_list(np.array([])) == []
    assert _polygon_to_list([[1.8, 2.2], [3.9, 4.1]]) == [[1, 2], [3, 4]]


def test_polygons_are_sorted_in_reading_order_and_padded() -> None:
    bottom = [[30, 50], [80, 50], [80, 60], [30, 60]]
    top_right = [[90, 10], [140, 10], [140, 20], [90, 20]]
    top_left = [[10, 11], [70, 11], [70, 21], [10, 21]]

    assert _sort_polygons([bottom, top_right, top_left]) == [
        top_left,
        top_right,
        bottom,
    ]
    assert _polygon_to_horizontal_box(
        top_left,
        image_width=100,
        image_height=100,
        padding_ratio=0.2,
    ) == [8, 72, 9, 23]
    assert _polygon_to_horizontal_box(
        [[0, 0], [0, 0], [0, 0], [0, 0]],
        image_width=1,
        image_height=1,
        padding_ratio=0,
    ) == [0, 1, 0, 1]
    lines = [
        SimpleNamespace(polygon=bottom),
        SimpleNamespace(polygon=top_right),
        SimpleNamespace(polygon=top_left),
    ]
    assert _sort_lines(lines) == [lines[2], lines[1], lines[0]]


def test_device_resolution_respects_explicit_device(monkeypatch) -> None:
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)

    assert PaddleOCREngine._resolve_device("cpu") == "cpu"
    assert PaddleOCREngine._resolve_device("gpu:1") == "gpu:1"
    assert PaddleOCREngine._resolve_device("auto") == "gpu:0"

    monkeypatch.setattr("torch.cuda.is_available", lambda: False)
    assert PaddleOCREngine._resolve_device("auto") == "cpu"


def test_pipeline_is_initialized_lazily_once(monkeypatch) -> None:
    calls = []
    sentinel = object()

    def fake_paddle_ocr(**kwargs):
        calls.append(kwargs)
        return sentinel

    monkeypatch.setattr("paddleocr.PaddleOCR", fake_paddle_ocr)
    settings = Settings(
        detector_model="det-test",
        recognizer_model="rec-test",
        recognition_backend="paddle",
        ocr_engine="transformers",
        ocr_device="cpu",
    )
    engine = PaddleOCREngine(settings)

    assert engine._get_pipeline() is sentinel
    assert engine._get_pipeline() is sentinel
    assert len(calls) == 1
    assert calls[0] == {
        "text_detection_model_name": "det-test",
        "text_recognition_model_name": "rec-test",
        "engine": "transformers",
        "device": "cpu",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "text_recognition_batch_size": 1,
    }


def test_pipeline_initialization_error_is_wrapped(monkeypatch) -> None:
    def fail(**kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("paddleocr.PaddleOCR", fail)
    engine = PaddleOCREngine(
        Settings(ocr_device="cpu", recognition_backend="paddle")
    )

    with pytest.raises(OCRProcessingError, match="model unavailable"):
        engine._get_pipeline()


def test_paddle_result_is_normalized_from_numpy_arrays() -> None:
    class FakePipeline:
        def predict(self, image, text_rec_score_thresh):
            assert image.shape == (100, 200, 3)
            assert text_rec_score_thresh == 0.5
            return [
                {
                    "res": {
                        "rec_texts": ["Điều 1", "", "Thanh toán"],
                        "rec_scores": np.array([0.99, 0.2, 0.88]),
                        "rec_polys": np.array(
                            [
                                [[1, 2], [10, 2], [10, 8], [1, 8]],
                                [[0, 0], [0, 0], [0, 0], [0, 0]],
                                [[4, 20], [80, 20], [80, 30], [4, 30]],
                            ]
                        ),
                    }
                }
            ]

    engine = PaddleOCREngine(
        Settings(ocr_device="cpu", recognition_backend="paddle")
    )
    engine._pipeline = FakePipeline()

    page = engine.recognize_page(
        np.zeros((100, 200, 3), dtype=np.uint8),
        page_number=1,
        score_threshold=0.5,
    )

    assert page.page_number == 1
    assert page.width == 200
    assert [line.text for line in page.lines] == ["Điều 1", "Thanh toán"]
    assert page.lines[0].polygon == [[1, 2], [10, 2], [10, 8], [1, 8]]


def test_recognize_page_handles_empty_and_partial_results() -> None:
    image = np.zeros((50, 70, 3), dtype=np.uint8)
    engine = PaddleOCREngine(
        Settings(ocr_device="cpu", recognition_backend="paddle")
    )
    engine._pipeline = SimpleNamespace(predict=lambda *args, **kwargs: [])

    empty_page = engine.recognize_page(image, 2, 0.4)

    assert empty_page.page_number == 2
    assert empty_page.width == 70
    assert empty_page.height == 50
    assert empty_page.lines == []

    engine._pipeline = SimpleNamespace(
        predict=lambda *args, **kwargs: [{"rec_texts": [" A ", "B"]}]
    )
    partial_page = engine.recognize_page(image, 3, 0.4)

    assert [line.text for line in partial_page.lines] == ["A", "B"]
    assert [line.confidence for line in partial_page.lines] == [0.0, 0.0]
    assert [line.polygon for line in partial_page.lines] == [[], []]


def test_inference_error_is_wrapped_with_page_number() -> None:
    class FailingPipeline:
        def predict(self, *args, **kwargs):
            raise RuntimeError("out of memory")

    engine = PaddleOCREngine(
        Settings(ocr_device="cpu", recognition_backend="paddle")
    )
    engine._pipeline = FailingPipeline()

    with pytest.raises(
        OCRProcessingError,
        match=r"trang 7.*out of memory",
    ):
        engine.recognize_page(
            np.zeros((10, 10, 3), dtype=np.uint8),
            page_number=7,
            score_threshold=0.5,
        )


def test_easyocr_models_are_initialized_lazily_once(monkeypatch) -> None:
    detector_calls = []
    reader_calls = []
    detector = object()
    reader = object()

    monkeypatch.setattr(
        "paddleocr.TextDetection",
        lambda **kwargs: detector_calls.append(kwargs) or detector,
    )
    monkeypatch.setattr(
        "easyocr.Reader",
        lambda *args, **kwargs: reader_calls.append((args, kwargs)) or reader,
    )
    engine = PaddleOCREngine(
        Settings(
            detector_model="det-test",
            ocr_engine="transformers",
            ocr_device="cpu",
            easyocr_languages=("vi", "en"),
        )
    )

    assert engine._get_detector() is detector
    assert engine._get_detector() is detector
    assert engine._get_easyocr_reader() is reader
    assert engine._get_easyocr_reader() is reader
    assert detector_calls == [
        {
            "model_name": "det-test",
            "engine": "transformers",
            "device": "cpu",
        }
    ]
    assert reader_calls == [
        ((["vi", "en"],), {"gpu": False, "detector": False, "verbose": False})
    ]
    assert engine.recognizer_label == "EasyOCR (vi,en)"


def test_easyocr_recognition_sorts_boxes_pads_and_filters_scores() -> None:
    class FakeDetector:
        def predict(self, image):
            assert image.shape == (100, 200, 3)
            return [
                {
                    "res": {
                        "dt_polys": [
                            [[10, 50], [90, 50], [90, 60], [10, 60]],
                            [[20, 10], [80, 10], [80, 20], [20, 20]],
                        ]
                    }
                }
            ]

    class FakeReader:
        def recognize(self, image, **kwargs):
            assert image.shape == (100, 200, 3)
            assert kwargs["horizontal_list"] == [
                [18, 82, 8, 22],
                [8, 92, 48, 62],
            ]
            assert kwargs["batch_size"] == 4
            return [
                [[[18, 8], [82, 8], [82, 22], [18, 22]], " Độc lập ", 0.8],
                [[[8, 48], [92, 48], [92, 62], [8, 62]], "mờ", 0.1],
            ]

    engine = PaddleOCREngine(
        Settings(
            ocr_device="cpu",
            recognition_batch_size=4,
            crop_padding_ratio=0.1,
        )
    )
    engine._detector = FakeDetector()
    engine._easyocr_reader = FakeReader()

    page = engine.recognize_page(
        np.zeros((100, 200, 3), dtype=np.uint8),
        page_number=2,
        score_threshold=0.2,
    )

    assert page.page_number == 2
    assert [line.text for line in page.lines] == ["Độc lập"]
    assert page.lines[0].confidence == 0.8
    assert page.lines[0].polygon == [[18, 8], [82, 8], [82, 22], [18, 22]]


def test_easyocr_handles_empty_detection_and_wraps_errors() -> None:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    engine = PaddleOCREngine(Settings(ocr_device="cpu"))
    engine._detector = SimpleNamespace(predict=lambda image: [])
    engine._easyocr_reader = SimpleNamespace(recognize=lambda *args, **kwargs: [])

    page = engine.recognize_page(image, page_number=1, score_threshold=0.2)
    assert page.lines == []

    engine._detector = SimpleNamespace(
        predict=lambda image: (_ for _ in ()).throw(RuntimeError("detector failed"))
    )
    with pytest.raises(OCRProcessingError, match=r"trang 3.*detector failed"):
        engine.recognize_page(image, page_number=3, score_threshold=0.2)


def test_unknown_recognition_backend_is_rejected() -> None:
    engine = PaddleOCREngine(
        Settings(ocr_device="cpu", recognition_backend="unknown")
    )

    with pytest.raises(OCRProcessingError, match="không được hỗ trợ"):
        engine.recognize_page(
            np.zeros((10, 10, 3), dtype=np.uint8),
            page_number=1,
            score_threshold=0.2,
        )
