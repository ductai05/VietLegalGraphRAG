from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .config import Settings
from .exceptions import GeminiAnalysisError
from .prompts import (
    CONTRACT_CHUNK_PROMPT,
    CONTRACT_REVIEW_PROMPT,
    CONTRACT_SYNTHESIS_PROMPT,
)


ProgressCallback = Callable[[int, int, str], None]


def split_contract_text(text: str, chunk_size: int) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    paragraphs = normalized.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    def flush() -> None:
        nonlocal current, current_length
        if current:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_length = 0

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > chunk_size:
            flush()
            for start in range(0, len(paragraph), chunk_size):
                chunks.append(paragraph[start : start + chunk_size])
            continue

        extra_length = len(paragraph) + (2 if current else 0)
        if current and current_length + extra_length > chunk_size:
            flush()
        current.append(paragraph)
        current_length += extra_length

    flush()
    return chunks


class GeminiContractAnalyzer:
    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory

    def _create_client(self, api_key: str) -> Any:
        if self._client_factory is not None:
            return self._client_factory(api_key)
        try:
            from google import genai
        except ImportError as exc:
            raise GeminiAnalysisError(
                "Thiếu package google-genai. Hãy cài requirements của app."
            ) from exc
        return genai.Client(api_key=api_key)

    def _generate(self, client: Any, model: str, prompt: str) -> str:
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=self.settings.gemini_max_output_tokens,
            )
        except (ImportError, AttributeError):
            config = None

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                kwargs = {
                    "model": model,
                    "contents": prompt,
                }
                if config is not None:
                    kwargs["config"] = config
                response = client.models.generate_content(**kwargs)
                response_text = getattr(response, "text", None)
                if not response_text:
                    raise GeminiAnalysisError(
                        "Gemini không trả về nội dung. Có thể phản hồi bị chặn "
                        "bởi bộ lọc an toàn hoặc model không khả dụng."
                    )
                return str(response_text).strip()
            except GeminiAnalysisError:
                raise
            except Exception as exc:
                last_error = exc
                message = str(exc).upper()
                retryable = any(
                    marker in message
                    for marker in ("429", "500", "502", "503", "504", "UNAVAILABLE")
                )
                if not retryable or attempt == 2:
                    break
                time.sleep(2**attempt)

        raise GeminiAnalysisError(
            f"Không thể gọi Gemini API: {last_error}"
        ) from last_error

    def analyze(
        self,
        contract_text: str,
        api_key: str,
        model: str,
        progress_callback: ProgressCallback | None = None,
    ) -> str:
        text = contract_text.strip()
        if not text:
            raise GeminiAnalysisError(
                "Chưa có văn bản OCR để gửi sang Gemini."
            )

        resolved_key = api_key.strip() or self.settings.gemini_api_key.strip()
        if not resolved_key:
            raise GeminiAnalysisError(
                "Hãy nhập Gemini API key hoặc đặt biến môi trường GEMINI_API_KEY."
            )

        resolved_model = model.strip() or self.settings.gemini_model
        chunks = split_contract_text(text, self.settings.gemini_chunk_chars)
        if len(chunks) > self.settings.gemini_max_chunks:
            capacity = (
                self.settings.gemini_chunk_chars * self.settings.gemini_max_chunks
            )
            raise GeminiAnalysisError(
                "Văn bản quá dài cho cấu hình hiện tại "
                f"({len(text):,} ký tự, giới hạn khoảng {capacity:,}). "
                "Tăng GEMINI_MAX_CHUNKS hoặc giảm số trang OCR."
            )

        client = self._create_client(resolved_key)
        if len(chunks) == 1:
            if progress_callback:
                progress_callback(1, 1, "Đang phân tích hợp đồng bằng Gemini")
            prompt = CONTRACT_REVIEW_PROMPT.format(contract_text=chunks[0])
            return self._generate(client, resolved_model, prompt)

        notes = []
        for index, chunk in enumerate(chunks, start=1):
            if progress_callback:
                progress_callback(
                    index,
                    len(chunks) + 1,
                    f"Gemini đang đọc phần {index}/{len(chunks)}",
                )
            prompt = CONTRACT_CHUNK_PROMPT.format(
                chunk_index=index,
                chunk_count=len(chunks),
                contract_text=chunk,
            )
            notes.append(
                f"## Phần {index}\n{self._generate(client, resolved_model, prompt)}"
            )

        if progress_callback:
            progress_callback(
                len(chunks) + 1,
                len(chunks) + 1,
                "Đang tổng hợp các rủi ro",
            )
        synthesis_prompt = CONTRACT_SYNTHESIS_PROMPT.format(
            chunk_count=len(chunks),
            chunk_notes="\n\n".join(notes),
        )
        return self._generate(client, resolved_model, synthesis_prompt)
