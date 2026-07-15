from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _getenv_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _getenv_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def _getenv_positive_int_maybe_invalid(name: str, default: int) -> tuple[int, bool]:
    """Parse a positive-int env var. Returns (value, invalid) where invalid=True
    when the user set a value that was non-positive or unparseable."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default, False
    try:
        parsed = int(raw.strip())
    except ValueError:
        return default, True
    if parsed <= 0:
        return default, True
    return parsed, False


def _getenv_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    elasticsearch_url: str
    elasticsearch_api_key: str | None
    elasticsearch_username: str | None
    elasticsearch_password: str | None
    elasticsearch_index: str
    elasticsearch_alias: str
    elasticsearch_verify_certs: bool
    elasticsearch_request_timeout: int
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str | None
    neo4j_database: str
    rerank_provider: str
    rerank_model: str
    rerank_model_allowlist: tuple[str, ...]
    voyage_api_key: str | None
    jina_api_key: str | None
    embedding_provider: str  # "hf" (PyTorch) or "onnx"
    embedding_model: str
    embedding_device: str
    embedding_cache_dir: str | None
    embedding_max_length: int
    embedding_dims: int
    embedding_onnx_model_path: str | None
    embedding_onnx_tokenizer_path: str | None
    dense_num_candidates_factor: int
    dense_num_candidates_factor_invalid: bool
    dense_min_num_candidates: int
    dense_min_num_candidates_invalid: bool
    llm_provider: str
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str
    llm_max_tokens: int
    frontend_origin: str
    runtime_fallback_enabled: bool
    ocr_provider: str
    ocr_max_file_mb: int
    ocr_max_file_bytes: int
    ocr_max_pdf_pages: int
    ocr_allowed_mime_types: tuple[str, ...]
    ocr_language_hints: tuple[str, ...]
    ocr_max_file_mb_invalid: bool
    ocr_config_invalid: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _factor, _factor_invalid = _getenv_positive_int_maybe_invalid(
        "DENSE_NUM_CANDIDATES_FACTOR", 4
    )
    _min, _min_invalid = _getenv_positive_int_maybe_invalid(
        "DENSE_MIN_NUM_CANDIDATES", 100
    )
    _ocr_max_mb, _ocr_mb_invalid = _getenv_positive_int_maybe_invalid(
        "OCR_MAX_FILE_MB", 10
    )
    return Settings(
        elasticsearch_url=os.getenv("ELASTICSEARCH_URL", "http://localhost:9200"),
        elasticsearch_api_key=os.getenv("ELASTICSEARCH_API_KEY") or os.getenv("ELASTIC_API_KEY"),
        elasticsearch_username=os.getenv("ELASTICSEARCH_USERNAME") or os.getenv("ELASTIC_USERNAME"),
        elasticsearch_password=os.getenv("ELASTICSEARCH_PASSWORD") or os.getenv("ELASTIC_PASSWORD"),
        elasticsearch_index=os.getenv("ELASTICSEARCH_INDEX", "vietlegal_chunks_hybrid_v1"),
        elasticsearch_alias=os.getenv("ELASTICSEARCH_ALIAS", "vietlegal_chunks"),
        elasticsearch_verify_certs=_getenv_bool("ELASTICSEARCH_VERIFY_CERTS", True),
        elasticsearch_request_timeout=_getenv_int("ELASTICSEARCH_REQUEST_TIMEOUT", 60),
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD"),
        neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        rerank_provider=os.getenv("RERANK_PROVIDER", "noop"),
        rerank_model=os.getenv("RERANK_MODEL", "rerank-2.5"),
        # Client-requested rerank models must be in this allowlist ("*" allows any).
        rerank_model_allowlist=_getenv_csv(
            "RERANK_MODEL_ALLOWLIST",
            ("rerank-2.5", "rerank-2.5-lite"),
        ),
        voyage_api_key=os.getenv("VOYAGE_API_KEY"),
        jina_api_key=os.getenv("JINA_API_KEY"),
        # Embedding provider: "hf" (PyTorch, default) or "onnx" (onnxruntime, no torch).
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "hf") or "hf",
        # Dense retrieval uses the same local HF model used to embed the corpus.
        embedding_model=(
            os.getenv("EMBEDDING_MODEL", "darklethelong/vnlegal-lal")
            or "darklethelong/vnlegal-lal"
        ),
        embedding_device=os.getenv("EMBEDDING_DEVICE", "auto") or "auto",
        embedding_cache_dir=os.getenv("EMBEDDING_CACHE_DIR") or None,
        embedding_max_length=_getenv_int("EMBEDDING_MAX_LENGTH", 1024),
        # Expected query-vector dims; 0 = use the local model default.
        embedding_dims=_getenv_int("EMBEDDING_DIMS", 0),
        # ONNX model paths (used when EMBEDDING_PROVIDER=onnx).
        embedding_onnx_model_path=os.getenv("EMBEDDING_ONNX_MODEL_PATH") or None,
        embedding_onnx_tokenizer_path=os.getenv("EMBEDDING_ONNX_TOKENIZER_PATH") or None,
        dense_num_candidates_factor=_factor,
        dense_num_candidates_factor_invalid=_factor_invalid,
        dense_min_num_candidates=_min,
        dense_min_num_candidates_invalid=_min_invalid,
        llm_provider=os.getenv("LLM_PROVIDER", "extractive"),
        llm_base_url=os.getenv("LLM_BASE_URL"),
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        llm_max_tokens=_getenv_int("LLM_MAX_TOKENS", 2048),
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
        runtime_fallback_enabled=_getenv_bool("RUNTIME_FALLBACK_ENABLED", True),
        # OCR: "none" disables the route; "google" uses Google Vision.
        ocr_provider=os.getenv("OCR_PROVIDER", "none"),
        ocr_max_file_mb=_ocr_max_mb,
        ocr_max_file_bytes=_ocr_max_mb * 1024 * 1024,
        ocr_max_pdf_pages=_getenv_int("OCR_MAX_PDF_PAGES", 5),
        ocr_allowed_mime_types=_getenv_csv(
            "OCR_ALLOWED_MIME_TYPES",
            ("image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"),
        ),
        ocr_language_hints=_getenv_csv(
            "OCR_LANGUAGE_HINTS",
            ("vi", "en"),
        ),
        ocr_max_file_mb_invalid=_ocr_mb_invalid,
        ocr_config_invalid=_ocr_mb_invalid,
    )
