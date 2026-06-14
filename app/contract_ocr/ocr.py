from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from statistics import median
from typing import Any

import numpy as np

from .config import Settings
from .exceptions import OCRProcessingError
from .models import OCRLine, OCRPage


def _to_plain_mapping(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        data = dict(result)
    else:
        data = {}
        for attribute in ("json", "res"):
            value = getattr(result, attribute, None)
            if callable(value):
                value = value()
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    continue
            if isinstance(value, Mapping):
                data = dict(value)
                break

    nested = data.get("res")
    if isinstance(nested, Mapping):
        return dict(nested)
    return data


def _polygon_to_list(polygon: Any) -> list[list[int]]:
    if polygon is None:
        return []
    array = np.asarray(polygon)
    if array.size == 0:
        return []
    return array.astype(int).reshape(-1, 2).tolist()


def _to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    return list(value)


def _sort_polygons(polygons: list[Any]) -> list[Any]:
    if len(polygons) < 2:
        return polygons

    entries = []
    heights = []
    for polygon in polygons:
        points = np.asarray(polygon, dtype=float).reshape(-1, 2)
        min_x = float(points[:, 0].min())
        min_y = float(points[:, 1].min())
        max_y = float(points[:, 1].max())
        center_y = (min_y + max_y) / 2
        height = max(1.0, max_y - min_y)
        entries.append((center_y, min_x, polygon))
        heights.append(height)

    tolerance = max(2.0, median(heights) * 0.5)
    entries.sort(key=lambda item: (item[0], item[1]))
    rows: list[list[tuple[float, float, Any]]] = []
    row_centers: list[float] = []
    for entry in entries:
        if not rows or abs(entry[0] - row_centers[-1]) > tolerance:
            rows.append([entry])
            row_centers.append(entry[0])
            continue
        rows[-1].append(entry)
        row_centers[-1] = sum(item[0] for item in rows[-1]) / len(rows[-1])

    ordered = []
    for row in rows:
        row.sort(key=lambda item: item[1])
        ordered.extend(item[2] for item in row)
    return ordered


def _polygon_to_horizontal_box(
    polygon: Any,
    image_width: int,
    image_height: int,
    padding_ratio: float,
) -> list[int]:
    points = np.asarray(polygon, dtype=float).reshape(-1, 2)
    min_x = float(points[:, 0].min())
    max_x = float(points[:, 0].max())
    min_y = float(points[:, 1].min())
    max_y = float(points[:, 1].max())
    line_height = max(1.0, max_y - min_y)
    padding = max(2, int(round(line_height * max(0.0, padding_ratio))))

    x0 = max(0, int(np.floor(min_x - padding)))
    x1 = min(image_width, int(np.ceil(max_x + padding)))
    y0 = max(0, int(np.floor(min_y - padding)))
    y1 = min(image_height, int(np.ceil(max_y + padding)))
    if x1 <= x0:
        x1 = min(image_width, x0 + 1)
    if y1 <= y0:
        y1 = min(image_height, y0 + 1)
    return [x0, x1, y0, y1]


def _sort_lines(lines: list[OCRLine]) -> list[OCRLine]:
    if len(lines) < 2 or any(not line.polygon for line in lines):
        return lines
    buckets: dict[tuple[tuple[int, int], ...], list[OCRLine]] = {}
    for line in lines:
        key = tuple(tuple(point) for point in line.polygon)
        buckets.setdefault(key, []).append(line)

    ordered = []
    for polygon in _sort_polygons([line.polygon for line in lines]):
        key = tuple(tuple(point) for point in polygon)
        ordered.append(buckets[key].pop(0))
    return ordered


class PaddleOCREngine:
    """PP-OCRv6 detector with selectable, process-local text recognition."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pipeline: Any | None = None
        self._detector: Any | None = None
        self._easyocr_reader: Any | None = None
        self._init_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._device = self._resolve_device(settings.ocr_device)

    @property
    def device(self) -> str:
        return self._device

    @property
    def recognizer_label(self) -> str:
        if self.settings.recognition_backend == "easyocr":
            languages = ",".join(self.settings.easyocr_languages)
            return f"EasyOCR ({languages})"
        return self.settings.recognizer_model

    @staticmethod
    def _resolve_device(configured_device: str) -> str:
        if configured_device.lower() != "auto":
            return configured_device
        try:
            import torch

            return "gpu:0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        with self._init_lock:
            if self._pipeline is not None:
                return self._pipeline
            try:
                from paddleocr import PaddleOCR

                self._pipeline = PaddleOCR(
                    text_detection_model_name=self.settings.detector_model,
                    text_recognition_model_name=self.settings.recognizer_model,
                    engine=self.settings.ocr_engine,
                    device=self._device,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    text_recognition_batch_size=1,
                )
            except Exception as exc:
                raise OCRProcessingError(
                    "Không thể khởi tạo PaddleOCR. Kiểm tra dependencies, "
                    "kết nối tải model và cấu hình GPU/CPU. "
                    f"Chi tiết: {exc}"
                ) from exc
        return self._pipeline

    def _get_detector(self) -> Any:
        if self._detector is not None:
            return self._detector

        with self._init_lock:
            if self._detector is not None:
                return self._detector
            try:
                from paddleocr import TextDetection

                self._detector = TextDetection(
                    model_name=self.settings.detector_model,
                    engine=self.settings.ocr_engine,
                    device=self._device,
                )
            except Exception as exc:
                raise OCRProcessingError(
                    "Không thể khởi tạo PP-OCRv6 detector. Kiểm tra "
                    f"dependencies, model và cấu hình GPU/CPU. Chi tiết: {exc}"
                ) from exc
        return self._detector

    def _get_easyocr_reader(self) -> Any:
        if self._easyocr_reader is not None:
            return self._easyocr_reader

        with self._init_lock:
            if self._easyocr_reader is not None:
                return self._easyocr_reader
            try:
                import easyocr

                self._easyocr_reader = easyocr.Reader(
                    list(self.settings.easyocr_languages),
                    gpu=self._device != "cpu",
                    detector=False,
                    verbose=False,
                )
            except Exception as exc:
                raise OCRProcessingError(
                    "Không thể khởi tạo EasyOCR recognizer tiếng Việt. "
                    f"Kiểm tra dependencies, model và GPU/CPU. Chi tiết: {exc}"
                ) from exc
        return self._easyocr_reader

    def recognize_page(
        self,
        image: np.ndarray,
        page_number: int,
        score_threshold: float,
    ) -> OCRPage:
        backend = self.settings.recognition_backend
        if backend == "easyocr":
            return self._recognize_page_easyocr(
                image,
                page_number=page_number,
                score_threshold=score_threshold,
            )
        if backend == "paddle":
            return self._recognize_page_paddle(
                image,
                page_number=page_number,
                score_threshold=score_threshold,
            )
        raise OCRProcessingError(
            f"OCR_RECOGNITION_BACKEND không được hỗ trợ: {backend!r}. "
            "Dùng 'easyocr' hoặc 'paddle'."
        )

    def _recognize_page_paddle(
        self,
        image: np.ndarray,
        page_number: int,
        score_threshold: float,
    ) -> OCRPage:
        pipeline = self._get_pipeline()
        try:
            with self._inference_lock:
                results = pipeline.predict(
                    image,
                    text_rec_score_thresh=float(score_threshold),
                )
        except Exception as exc:
            raise OCRProcessingError(
                f"OCR thất bại ở trang {page_number}: {exc}"
            ) from exc

        if not results:
            return OCRPage(
                page_number=page_number,
                width=int(image.shape[1]),
                height=int(image.shape[0]),
            )

        data = _to_plain_mapping(results[0])
        texts = _to_list(data.get("rec_texts"))
        scores = _to_list(data.get("rec_scores"))
        polygons = _to_list(data.get("rec_polys"))

        lines = []
        for index, text in enumerate(texts):
            normalized_text = str(text).strip()
            if not normalized_text:
                continue
            score = float(scores[index]) if index < len(scores) else 0.0
            polygon = polygons[index] if index < len(polygons) else None
            lines.append(
                OCRLine(
                    text=normalized_text,
                    confidence=score,
                    polygon=_polygon_to_list(polygon),
                )
            )

        return OCRPage(
            page_number=page_number,
            width=int(image.shape[1]),
            height=int(image.shape[0]),
            lines=_sort_lines(lines),
        )

    def _recognize_page_easyocr(
        self,
        image: np.ndarray,
        page_number: int,
        score_threshold: float,
    ) -> OCRPage:
        detector = self._get_detector()
        recognizer = self._get_easyocr_reader()
        try:
            with self._inference_lock:
                detection_results = detector.predict(image)
                detection_data = (
                    _to_plain_mapping(detection_results[0])
                    if detection_results
                    else {}
                )
                polygons = _sort_polygons(
                    _to_list(detection_data.get("dt_polys"))
                )
                if not polygons:
                    recognition_results = []
                else:
                    height, width = image.shape[:2]
                    boxes = [
                        _polygon_to_horizontal_box(
                            polygon,
                            image_width=width,
                            image_height=height,
                            padding_ratio=self.settings.crop_padding_ratio,
                        )
                        for polygon in polygons
                    ]
                    recognition_results = recognizer.recognize(
                        image,
                        horizontal_list=boxes,
                        free_list=[],
                        detail=1,
                        batch_size=self.settings.recognition_batch_size,
                        paragraph=False,
                    )
        except Exception as exc:
            raise OCRProcessingError(
                f"OCR thất bại ở trang {page_number}: {exc}"
            ) from exc

        lines = []
        for result in recognition_results:
            if len(result) < 3:
                continue
            polygon, text, confidence = result[:3]
            normalized_text = str(text).strip()
            score = float(confidence)
            if not normalized_text or score < float(score_threshold):
                continue
            lines.append(
                OCRLine(
                    text=normalized_text,
                    confidence=score,
                    polygon=_polygon_to_list(polygon),
                )
            )

        return OCRPage(
            page_number=page_number,
            width=int(image.shape[1]),
            height=int(image.shape[0]),
            lines=_sort_lines(lines),
        )
