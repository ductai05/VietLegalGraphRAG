from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config import Settings  # noqa: E402
from dependencies import (  # noqa: E402
    _build_dense_retriever,
    _build_embedder,
    _build_graph_chunk_fetcher,
    _mapping_vector_dims,
)
from retrieval_modes import RetrievalRequest  # noqa: E402


def _settings(**overrides) -> Settings:
    values = dict(
        elasticsearch_url="http://localhost:9200",
        elasticsearch_api_key=None,
        elasticsearch_username=None,
        elasticsearch_password=None,
        elasticsearch_index="vietlegal_chunks_hybrid_v1",
        elasticsearch_alias="vietlegal_chunks",
        elasticsearch_verify_certs=True,
        elasticsearch_request_timeout=60,
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password=None,
        neo4j_database="neo4j",
        rerank_provider="noop",
        rerank_model="rerank-2.5",
        rerank_model_allowlist=("rerank-2.5",),
        voyage_api_key=None,
        jina_api_key=None,
        embedding_provider="hf",
        embedding_model="darklethelong/vnlegal-lal",
        embedding_device="auto",
        embedding_cache_dir=None,
        embedding_max_length=1024,
        embedding_dims=0,
        embedding_onnx_model_path=None,
        embedding_onnx_tokenizer_path=None,
        dense_num_candidates_factor=4,
        dense_num_candidates_factor_invalid=False,
        dense_min_num_candidates=100,
        dense_min_num_candidates_invalid=False,
        llm_provider="extractive",
        llm_base_url=None,
        llm_api_key=None,
        llm_model="gpt-4o-mini",
        frontend_origin="http://localhost:5173",
        runtime_fallback_enabled=True,
        ocr_provider="none",
        ocr_max_file_mb=10,
        ocr_max_file_bytes=10 * 1024 * 1024,
        ocr_max_pdf_pages=5,
        ocr_allowed_mime_types=("image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"),
        ocr_language_hints=("vi", "en"),
        ocr_max_file_mb_invalid=False,
        ocr_config_invalid=False,
    )
    values.update(overrides)
    return Settings(**values)


def _mapping_response(dims: int | None, field_type: str = "dense_vector") -> dict:
    vector: dict = {"type": field_type}
    if dims is not None:
        vector["dims"] = dims
    return {
        "vietlegal_chunks_hybrid_v1": {
            "mappings": {"properties": {"vector": vector, "chunk_text": {"type": "text"}}}
        }
    }


# --- _mapping_vector_dims ---


def test_mapping_vector_dims_extracts_dims() -> None:
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(1024)
    assert _mapping_vector_dims(client, "vietlegal_chunks") == 1024
    client.indices.get_mapping.assert_called_once_with(index="vietlegal_chunks")


def test_mapping_vector_dims_none_when_field_missing() -> None:
    client = Mock()
    client.indices.get_mapping.return_value = {
        "idx": {"mappings": {"properties": {"chunk_text": {"type": "text"}}}}
    }
    assert _mapping_vector_dims(client, "idx") is None


def test_mapping_vector_dims_none_when_wrong_type() -> None:
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(None, field_type="keyword")
    assert _mapping_vector_dims(client, "idx") is None


# --- _build_embedder ---


def test_build_embedder_uses_local_hf_by_default_without_api_key() -> None:
    warnings: list[str] = []
    status: dict[str, str] = {}
    embedder = _build_embedder(_settings(), warnings, status)
    assert embedder is not None
    assert embedder.model == "darklethelong/vnlegal-lal"
    assert embedder.dims == 1024
    assert status["embedding"] == "local-hf"
    assert warnings == []


def test_build_embedder_passes_local_hf_runtime_options() -> None:
    warnings: list[str] = []
    status: dict[str, str] = {}
    settings = _settings(
        embedding_model="darklethelong/vnlegal-lal",
        embedding_device="cpu",
        embedding_cache_dir="/tmp/hf-cache",
        embedding_max_length=768,
        embedding_dims=1024,
    )
    embedder = _build_embedder(settings, warnings, status)
    assert embedder is not None
    assert embedder.model == "darklethelong/vnlegal-lal"
    assert embedder.device == "cpu"
    assert embedder.cache_dir == "/tmp/hf-cache"
    assert embedder.max_length == 768
    assert embedder.dims == 1024
    assert status["embedding"] == "local-hf"
    assert warnings == []


def test_build_embedder_ignores_voyage_api_key_for_embeddings() -> None:
    warnings: list[str] = []
    status: dict[str, str] = {}
    settings = _settings(voyage_api_key="voyage-key")
    embedder = _build_embedder(settings, warnings, status)
    assert embedder is not None
    assert embedder.model == "darklethelong/vnlegal-lal"
    assert embedder.dims == 1024
    assert status["embedding"] == "local-hf"
    assert warnings == []


# --- B5: _build_dense_retriever dim check ---


def _fake_embedder(dims: int | None):
    embedder = Mock()
    embedder.dims = dims
    return embedder


def test_dense_retriever_built_when_dims_match(monkeypatch) -> None:
    import dependencies

    monkeypatch.setattr(
        dependencies, "_build_embedder", lambda *args, **kwargs: _fake_embedder(1024)
    )
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(1024)
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(),
        warnings,
        status,
        client=client,
        index="vietlegal_chunks",
    )

    assert retriever is not None
    assert retriever.index == "vietlegal_chunks"
    assert warnings == []


def test_dense_retriever_uses_configured_num_candidates(monkeypatch) -> None:
    import dependencies

    embedder = _fake_embedder(1024)
    embedder.embed_query.return_value = [0.1, 0.2]
    monkeypatch.setattr(dependencies, "_build_embedder", lambda *args, **kwargs: embedder)
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(1024)
    client.search.return_value = {"hits": {"hits": []}}
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(
            dense_num_candidates_factor=9,
            dense_num_candidates_factor_invalid=False,
            dense_min_num_candidates=80,
            dense_min_num_candidates_invalid=False,
        ),
        warnings,
        status,
        client=client,
        index="idx",
    )

    assert retriever is not None
    assert retriever.num_candidates_factor == 9
    assert retriever.min_num_candidates == 80

    request = RetrievalRequest(query="q", top_k=1, rerank={"enabled": False})
    retriever.search(request, candidate_k=10)
    assert client.search.call_args.kwargs["knn"]["num_candidates"] == 90

    retriever.search(request, candidate_k=5)
    assert client.search.call_args.kwargs["knn"]["num_candidates"] == 80


def test_dense_disabled_on_dim_mismatch(monkeypatch) -> None:
    import dependencies

    monkeypatch.setattr(
        dependencies, "_build_embedder", lambda *args, **kwargs: _fake_embedder(1024)
    )
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(768)
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(),
        warnings,
        status,
        client=client,
        index="idx",
    )

    assert retriever is None
    assert "dense.dim_mismatch" in warnings
    assert status["embedding"] == "disabled"


def test_dense_disabled_when_vector_mapping_missing(monkeypatch) -> None:
    import dependencies

    monkeypatch.setattr(
        dependencies, "_build_embedder", lambda *args, **kwargs: _fake_embedder(1024)
    )
    client = Mock()
    client.indices.get_mapping.return_value = {
        "idx": {"mappings": {"properties": {}}}
    }
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(),
        warnings,
        status,
        client=client,
        index="idx",
    )

    assert retriever is None
    assert "dense.vector_mapping_missing" in warnings


def test_dense_disabled_when_mapping_check_fails(monkeypatch) -> None:
    import dependencies

    monkeypatch.setattr(
        dependencies, "_build_embedder", lambda *args, **kwargs: _fake_embedder(1024)
    )
    client = Mock()
    client.indices.get_mapping.side_effect = ConnectionError("boom")
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(),
        warnings,
        status,
        client=client,
        index="idx",
    )

    assert retriever is None
    assert "dense.mapping_check_failed" in warnings


def test_dense_skips_dim_check_for_unknown_embedder_dims(monkeypatch) -> None:
    import dependencies

    monkeypatch.setattr(
        dependencies, "_build_embedder", lambda *args, **kwargs: _fake_embedder(None)
    )
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(1024)
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(),
        warnings,
        status,
        client=client,
        index="idx",
    )

    assert retriever is not None
    assert warnings == []


def test_config_invalid_dense_factor_emits_warning(monkeypatch) -> None:
    import dependencies

    monkeypatch.setattr(
        dependencies, "_build_embedder", lambda *args, **kwargs: _fake_embedder(1024)
    )
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(1024)
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(dense_num_candidates_factor_invalid=True),
        warnings,
        status,
        client=client,
        index="idx",
    )

    assert retriever is not None
    assert "config.dense_num_candidates_factor_invalid" in warnings


def test_config_invalid_dense_min_emits_warning(monkeypatch) -> None:
    import dependencies

    monkeypatch.setattr(
        dependencies, "_build_embedder", lambda *args, **kwargs: _fake_embedder(1024)
    )
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(1024)
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(dense_min_num_candidates_invalid=True),
        warnings,
        status,
        client=client,
        index="idx",
    )

    assert retriever is not None
    assert "config.dense_min_num_candidates_invalid" in warnings


def test_config_invalid_factor_and_min_both_emit_warnings(monkeypatch) -> None:
    import dependencies

    monkeypatch.setattr(
        dependencies, "_build_embedder", lambda *args, **kwargs: _fake_embedder(1024)
    )
    client = Mock()
    client.indices.get_mapping.return_value = _mapping_response(1024)
    warnings: list[str] = []
    status: dict[str, str] = {}

    retriever = _build_dense_retriever(
        _settings(
            dense_num_candidates_factor_invalid=True,
            dense_min_num_candidates_invalid=True,
        ),
        warnings,
        status,
        client=client,
        index="idx",
    )

    assert retriever is not None
    assert "config.dense_num_candidates_factor_invalid" in warnings
    assert "config.dense_min_num_candidates_invalid" in warnings


def test_build_graph_chunk_fetcher_uses_elasticsearch_alias(monkeypatch) -> None:
    import types

    fake_client = Mock()
    fake_elasticsearch = types.ModuleType("elasticsearch")
    fake_elasticsearch.Elasticsearch = Mock(return_value=fake_client)
    monkeypatch.setitem(sys.modules, "elasticsearch", fake_elasticsearch)
    warnings: list[str] = []

    fetcher = _build_graph_chunk_fetcher(
        _settings(
            elasticsearch_url="https://es.example",
            elasticsearch_api_key="elastic-key",
            elasticsearch_alias="vietlegal_chunks",
            elasticsearch_index="vietlegal_chunks_hybrid_v1",
        ),
        warnings,
    )

    assert fetcher is not None
    assert fetcher.index == "vietlegal_chunks"
    assert warnings == []
    fake_elasticsearch.Elasticsearch.assert_called_once()
