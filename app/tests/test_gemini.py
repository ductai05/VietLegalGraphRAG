from __future__ import annotations

from types import SimpleNamespace

import pytest

from contract_ocr.config import Settings
from contract_ocr.exceptions import GeminiAnalysisError
from contract_ocr.gemini import GeminiContractAnalyzer, split_contract_text


class RecordingModels:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(text=response)


def _analyzer(settings: Settings, responses):
    models = RecordingModels(responses)
    keys = []

    def create_client(api_key: str):
        keys.append(api_key)
        return SimpleNamespace(models=models)

    return GeminiContractAnalyzer(settings, client_factory=create_client), models, keys


def test_split_contract_text_handles_empty_crlf_and_long_paragraphs() -> None:
    assert split_contract_text(" \r\n ", chunk_size=20) == []

    text = "Điều 1\r\nNội dung A\r\n\r\nĐiều 2\r\n" + ("B" * 25)
    chunks = split_contract_text(text, chunk_size=20)

    assert chunks
    assert "".join(chunks).replace("\n\n", "") == (
        text.replace("\r\n", "\n").strip().replace("\n\n", "")
    )
    assert all(len(chunk) <= 20 for chunk in chunks)


def test_analyzer_calls_single_request_for_short_contract() -> None:
    settings = Settings(gemini_chunk_chars=5_000)
    analyzer, models, keys = _analyzer(settings, ["Kết quả rà soát"])
    progress = []

    result = analyzer.analyze(
        "Hợp đồng thử nghiệm",
        api_key=" secret ",
        model="gemini-test",
        progress_callback=lambda *args: progress.append(args),
    )

    assert result == "Kết quả rà soát"
    assert keys == ["secret"]
    assert len(models.calls) == 1
    assert models.calls[0]["model"] == "gemini-test"
    assert "Hợp đồng thử nghiệm" in models.calls[0]["contents"]
    assert progress == [(1, 1, "Đang phân tích hợp đồng bằng Gemini")]


def test_analyzer_uses_server_key_and_default_model() -> None:
    settings = Settings(
        gemini_api_key="server-key",
        gemini_model="default-model",
        gemini_chunk_chars=5_000,
    )
    analyzer, models, keys = _analyzer(settings, ["OK"])

    assert analyzer.analyze("Nội dung", api_key="", model="") == "OK"
    assert keys == ["server-key"]
    assert models.calls[0]["model"] == "default-model"


def test_analyzer_processes_multiple_chunks_then_synthesizes() -> None:
    settings = Settings(gemini_chunk_chars=5_000, gemini_max_chunks=3)
    text = ("A" * 4_000) + "\n\n" + ("B" * 4_000)
    analyzer, models, _ = _analyzer(
        settings,
        ["Ghi chú A", "Ghi chú B", "Tổng hợp"],
    )
    progress = []

    result = analyzer.analyze(
        text,
        api_key="key",
        model="model",
        progress_callback=lambda *args: progress.append(args),
    )

    assert result == "Tổng hợp"
    assert len(models.calls) == 3
    assert "phần 1/2" in models.calls[0]["contents"]
    assert "phần 2/2" in models.calls[1]["contents"]
    assert "Ghi chú A" in models.calls[2]["contents"]
    assert "Ghi chú B" in models.calls[2]["contents"]
    assert [item[:2] for item in progress] == [(1, 3), (2, 3), (3, 3)]


def test_analyzer_validates_text_key_and_max_chunks_before_client_creation() -> None:
    settings = Settings(
        gemini_api_key="",
        gemini_chunk_chars=5_000,
        gemini_max_chunks=1,
    )
    analyzer, _, keys = _analyzer(settings, ["unused"])

    with pytest.raises(GeminiAnalysisError, match="văn bản OCR"):
        analyzer.analyze(" ", api_key="key", model="model")
    with pytest.raises(GeminiAnalysisError, match="API key"):
        analyzer.analyze("Nội dung", api_key="", model="model")
    with pytest.raises(GeminiAnalysisError, match="quá dài"):
        analyzer.analyze("X" * 5_001, api_key="key", model="model")

    assert keys == []


def test_generate_rejects_empty_response() -> None:
    analyzer, _, _ = _analyzer(Settings(), [None])

    with pytest.raises(GeminiAnalysisError, match="không trả về nội dung"):
        analyzer.analyze("Nội dung", api_key="key", model="model")


def test_generate_does_not_retry_non_retryable_error(monkeypatch) -> None:
    analyzer, models, _ = _analyzer(
        Settings(),
        [RuntimeError("invalid API key")],
    )
    sleeps = []
    monkeypatch.setattr("contract_ocr.gemini.time.sleep", sleeps.append)

    with pytest.raises(GeminiAnalysisError, match="invalid API key"):
        analyzer.analyze("Nội dung", api_key="key", model="model")

    assert len(models.calls) == 1
    assert sleeps == []


def test_generate_retries_transient_errors(monkeypatch) -> None:
    analyzer, models, _ = _analyzer(
        Settings(),
        [RuntimeError("503 unavailable"), RuntimeError("429"), "Thành công"],
    )
    sleeps = []
    monkeypatch.setattr("contract_ocr.gemini.time.sleep", sleeps.append)

    result = analyzer.analyze("Nội dung", api_key="key", model="model")

    assert result == "Thành công"
    assert len(models.calls) == 3
    assert sleeps == [1, 2]


def test_generate_stops_after_three_transient_failures(monkeypatch) -> None:
    analyzer, models, _ = _analyzer(
        Settings(),
        [RuntimeError("503"), RuntimeError("503"), RuntimeError("503")],
    )
    monkeypatch.setattr("contract_ocr.gemini.time.sleep", lambda delay: None)

    with pytest.raises(GeminiAnalysisError, match="503"):
        analyzer.analyze("Nội dung", api_key="key", model="model")

    assert len(models.calls) == 3
