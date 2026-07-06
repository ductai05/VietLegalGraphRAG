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
    return int(value)


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
    voyage_api_key: str | None
    llm_provider: str
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str
    frontend_origin: str
    runtime_fallback_enabled: bool


@lru_cache(maxsize=1)
def get_settings() -> Settings:
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
        voyage_api_key=os.getenv("VOYAGE_API_KEY"),
        llm_provider=os.getenv("LLM_PROVIDER", "extractive"),
        llm_base_url=os.getenv("LLM_BASE_URL"),
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
        runtime_fallback_enabled=_getenv_bool("RUNTIME_FALLBACK_ENABLED", True),
    )
