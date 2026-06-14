from contract_ocr.config import (
    Settings,
    _env_bool,
    _env_csv,
    _env_float,
    _env_int,
)


def test_environment_helpers_use_defaults_and_minimums(monkeypatch) -> None:
    monkeypatch.delenv("TEST_BOOL", raising=False)
    monkeypatch.delenv("TEST_INT", raising=False)
    monkeypatch.delenv("TEST_FLOAT", raising=False)

    assert _env_bool("TEST_BOOL", True) is True
    assert _env_int("TEST_INT", 7, minimum=5) == 7
    assert _env_float("TEST_FLOAT", 0.7, minimum=0.5) == 0.7
    assert _env_csv("TEST_CSV", ("vi", "en")) == ("vi", "en")

    monkeypatch.setenv("TEST_BOOL", "YES")
    monkeypatch.setenv("TEST_INT", "-10")
    monkeypatch.setenv("TEST_FLOAT", "-1.2")
    monkeypatch.setenv("TEST_CSV", " vi, en, ")

    assert _env_bool("TEST_BOOL", False) is True
    assert _env_int("TEST_INT", 7, minimum=5) == 5
    assert _env_float("TEST_FLOAT", 0.7, minimum=0.5) == 0.5
    assert _env_csv("TEST_CSV", ("fallback",)) == ("vi", "en")

    monkeypatch.setenv("TEST_CSV", " , ")
    assert _env_csv("TEST_CSV", ("fallback",)) == ("fallback",)


def test_settings_from_env_reads_and_clamps_values(monkeypatch) -> None:
    values = {
        "OCR_DETECTOR_MODEL": "det-test",
        "OCR_RECOGNIZER_MODEL": "rec-test",
        "OCR_RECOGNITION_BACKEND": "PADDLE",
        "OCR_EASYOCR_LANGUAGES": "vi,en",
        "OCR_RECOGNITION_BATCH_SIZE": "0",
        "OCR_CROP_PADDING_RATIO": "-1",
        "OCR_ENGINE": "transformers",
        "OCR_DEVICE": "cpu",
        "OCR_TEXT_SCORE_THRESHOLD": "-1",
        "PDF_DPI": "10",
        "MAX_PDF_DPI": "20",
        "MAX_PDF_PAGES": "0",
        "MAX_UPLOAD_MB": "2",
        "GEMINI_MODEL": "gemini-test",
        "GEMINI_API_KEY": "server-secret",
        "GEMINI_CHUNK_CHARS": "10",
        "GEMINI_MAX_CHUNKS": "0",
        "GEMINI_MAX_OUTPUT_TOKENS": "100",
        "GRADIO_SERVER_NAME": "0.0.0.0",
        "GRADIO_SERVER_PORT": "9000",
        "GRADIO_SHARE": "on",
        "GRADIO_QUEUE_SIZE": "0",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.detector_model == "det-test"
    assert settings.recognizer_model == "rec-test"
    assert settings.recognition_backend == "paddle"
    assert settings.easyocr_languages == ("vi", "en")
    assert settings.recognition_batch_size == 1
    assert settings.crop_padding_ratio == 0.0
    assert settings.ocr_device == "cpu"
    assert settings.text_rec_score_threshold == 0.0
    assert settings.default_pdf_dpi == 96
    assert settings.max_pdf_dpi == 96
    assert settings.max_pages == 1
    assert settings.max_upload_mb == 2
    assert settings.gemini_model == "gemini-test"
    assert settings.gemini_api_key == "server-secret"
    assert settings.gemini_chunk_chars == 5_000
    assert settings.gemini_max_chunks == 1
    assert settings.gemini_max_output_tokens == 512
    assert settings.server_name == "0.0.0.0"
    assert settings.server_port == 9000
    assert settings.gradio_share is True
    assert settings.queue_size == 1
