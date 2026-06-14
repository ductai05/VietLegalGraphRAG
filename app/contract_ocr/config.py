from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    value = float(os.getenv(name, str(default)))
    return max(minimum, value)


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


@dataclass(frozen=True, slots=True)
class Settings:
    detector_model: str = "PP-OCRv6_medium_det"
    recognizer_model: str = "PP-OCRv6_medium_rec"
    recognition_backend: str = "easyocr"
    easyocr_languages: tuple[str, ...] = ("vi", "en")
    recognition_batch_size: int = 8
    crop_padding_ratio: float = 0.15
    ocr_engine: str = "transformers"
    ocr_device: str = "auto"
    text_rec_score_threshold: float = 0.2
    default_pdf_dpi: int = 180
    max_pdf_dpi: int = 300
    max_pages: int = 50
    max_upload_mb: int = 50
    gemini_model: str = "gemini-3.5-flash"
    gemini_api_key: str = ""
    gemini_chunk_chars: int = 30_000
    gemini_max_chunks: int = 12
    gemini_max_output_tokens: int = 4_096
    server_name: str = "127.0.0.1"
    server_port: int = 7860
    gradio_share: bool = False
    queue_size: int = 16

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            detector_model=os.getenv(
                "OCR_DETECTOR_MODEL", "PP-OCRv6_medium_det"
            ),
            recognizer_model=os.getenv(
                "OCR_RECOGNIZER_MODEL", "PP-OCRv6_medium_rec"
            ),
            recognition_backend=os.getenv(
                "OCR_RECOGNITION_BACKEND", "easyocr"
            ).strip().lower(),
            easyocr_languages=_env_csv(
                "OCR_EASYOCR_LANGUAGES", ("vi", "en")
            ),
            recognition_batch_size=_env_int(
                "OCR_RECOGNITION_BATCH_SIZE", 8
            ),
            crop_padding_ratio=_env_float(
                "OCR_CROP_PADDING_RATIO", 0.15
            ),
            ocr_engine=os.getenv("OCR_ENGINE", "transformers"),
            ocr_device=os.getenv("OCR_DEVICE", "auto"),
            text_rec_score_threshold=_env_float(
                "OCR_TEXT_SCORE_THRESHOLD", 0.2
            ),
            default_pdf_dpi=_env_int("PDF_DPI", 180, minimum=96),
            max_pdf_dpi=_env_int("MAX_PDF_DPI", 300, minimum=96),
            max_pages=_env_int("MAX_PDF_PAGES", 50),
            max_upload_mb=_env_int("MAX_UPLOAD_MB", 50),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_chunk_chars=_env_int("GEMINI_CHUNK_CHARS", 30_000, 5_000),
            gemini_max_chunks=_env_int("GEMINI_MAX_CHUNKS", 12),
            gemini_max_output_tokens=_env_int(
                "GEMINI_MAX_OUTPUT_TOKENS", 4_096, 512
            ),
            server_name=os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
            server_port=_env_int("GRADIO_SERVER_PORT", 7860),
            gradio_share=_env_bool("GRADIO_SHARE", False),
            queue_size=_env_int("GRADIO_QUEUE_SIZE", 16),
        )
