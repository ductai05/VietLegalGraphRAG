from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def reload_backend_modules() -> None:
    for name in [
        "config",
        "dependencies",
        "main",
        "routes.health",
        "routes.search",
    ]:
        if name in sys.modules:
            importlib.reload(sys.modules[name])


def test_settings_reads_runtime_provider_environment(monkeypatch) -> None:
    monkeypatch.setenv("ELASTICSEARCH_URL", "https://elastic.example")
    monkeypatch.setenv("ELASTICSEARCH_API_KEY", "elastic-key")
    monkeypatch.setenv("RERANK_PROVIDER", "voyage")
    monkeypatch.setenv("RERANK_MODEL", "rerank-2.5")
    monkeypatch.setenv("VOYAGE_API_KEY", "voyage-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "llm-key")
    monkeypatch.setenv("LLM_MODEL", "legal-model")

    reload_backend_modules()
    from config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.elasticsearch_url == "https://elastic.example"
    assert settings.elasticsearch_api_key == "elastic-key"
    assert settings.rerank_provider == "voyage"
    assert settings.rerank_model == "rerank-2.5"
    assert settings.voyage_api_key == "voyage-key"
    assert settings.llm_provider == "openai-compatible"
    assert settings.llm_base_url == "https://llm.example/v1"
    assert settings.llm_api_key == "llm-key"
    assert settings.llm_model == "legal-model"
    assert settings.embedding_model == "darklethelong/vnlegal-lal"
    assert settings.embedding_device == "auto"
    assert settings.embedding_max_length == 1024


def test_backend_imports_with_app_path_only() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_APP)
    for key in (
        "ELASTICSEARCH_URL",
        "ELASTICSEARCH_API_KEY",
        "ELASTICSEARCH_USERNAME",
        "ELASTICSEARCH_PASSWORD",
        "VOYAGE_API_KEY",
        "LLM_API_KEY",
        "NEO4J_PASSWORD",
    ):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, "-c", "import main; print(main.app.title)"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "VietLegalGraphRAG API" in result.stdout


def test_settings_dense_num_candidates_defaults(monkeypatch) -> None:
    monkeypatch.delenv("DENSE_NUM_CANDIDATES_FACTOR", raising=False)
    monkeypatch.delenv("DENSE_MIN_NUM_CANDIDATES", raising=False)

    reload_backend_modules()
    from config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.dense_num_candidates_factor == 4
    assert settings.dense_min_num_candidates == 100


def test_settings_dense_num_candidates_env_override(monkeypatch) -> None:
    monkeypatch.setenv("DENSE_NUM_CANDIDATES_FACTOR", "7")
    monkeypatch.setenv("DENSE_MIN_NUM_CANDIDATES", "250")

    reload_backend_modules()
    from config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.dense_num_candidates_factor == 7
    assert settings.dense_min_num_candidates == 250


def test_settings_dense_num_candidates_invalid_values_use_defaults(monkeypatch) -> None:
    monkeypatch.setenv("DENSE_NUM_CANDIDATES_FACTOR", "0")
    monkeypatch.setenv("DENSE_MIN_NUM_CANDIDATES", "-5")

    reload_backend_modules()
    from config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.dense_num_candidates_factor == 4
    assert settings.dense_min_num_candidates == 100


def test_settings_dense_num_candidates_malformed_values_use_defaults(monkeypatch) -> None:
    monkeypatch.setenv("DENSE_NUM_CANDIDATES_FACTOR", "many")
    monkeypatch.setenv("DENSE_MIN_NUM_CANDIDATES", "lots")

    reload_backend_modules()
    from config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.dense_num_candidates_factor == 4
    assert settings.dense_min_num_candidates == 100


def test_answer_endpoint_uses_degraded_fallback_without_external_credentials(monkeypatch) -> None:
    for key in [
        "ELASTICSEARCH_URL",
        "ELASTICSEARCH_API_KEY",
        "ELASTICSEARCH_USERNAME",
        "ELASTICSEARCH_PASSWORD",
        "RERANK_PROVIDER",
        "VOYAGE_API_KEY",
        "LLM_PROVIDER",
        "LLM_API_KEY",
        "NEO4J_PASSWORD",
    ]:
        monkeypatch.delenv(key, raising=False)

    reload_backend_modules()
    from config import get_settings
    from main import create_app

    get_settings.cache_clear()
    client = TestClient(create_app())

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["elasticsearch"] == "fallback"
    assert health.json()["llm"] == "extractive"
    assert health.json()["reranker"] == "noop"

    response = client.post(
        "/answer",
        json={"query": "Quy dinh ve cham dut hop dong?", "top_k": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"]
    assert payload["retrieval_context"]
    assert payload["retrieval_trace"]["runtime"] == "fallback"
    assert payload["retrieval_trace"]["lightrag_enabled"] is False
    assert "retrieval_trace" in payload


def test_elasticsearch_text_retriever_queries_hybrid_index_and_maps_hits() -> None:
    from elasticsearch_retriever import ElasticsearchTextRetriever
    from retrieval_modes import RetrievalRequest

    client = Mock()
    client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_score": 9.5,
                    "_source": {
                        "chunk_id": "chunk-1",
                        "doc_id": "doc-1",
                        "title": "Luat Dau tu",
                        "document_number": "61/2020/QH14",
                        "legal_type": "Luat",
                        "effect_status": "Con hieu luc",
                        "section_path": ["Dieu 1"],
                        "chunk_text": "Noi dung dieu 1",
                        "vector": [0.1, 0.2],
                    },
                }
            ]
        }
    }

    retriever = ElasticsearchTextRetriever(client, index="vietlegal_chunks")
    hits = retriever.search(
        RetrievalRequest(
            query="dau tu",
            retrieval_mode="hybrid",
            filters={"effect_status": "Con hieu luc"},
            top_k=1,
            rerank={"enabled": False},
        ),
        candidate_k=3,
    )

    assert hits[0].chunk_id == "chunk-1"
    assert hits[0].scores == {"bm25": 9.5}
    assert hits[0].citation == "61/2020/QH14 | Luat Dau tu | Dieu 1 | chunk_id: chunk-1"
    request = client.search.call_args.kwargs
    assert request["index"] == "vietlegal_chunks"
    assert request["size"] == 3
    assert request["source_excludes"] == ["vector"]
    assert request["query"]["bool"]["filter"] == [
        {"term": {"effect_status": "Con hieu luc"}}
    ]
    fields = request["query"]["bool"]["must"][0]["multi_match"]["fields"]
    assert "chunk_text^4" in fields
    assert "chunk_text_vi^4" in fields


def test_voyage_reranker_reorders_hits_and_records_scores() -> None:
    from contracts import RetrievalHit
    from rerank_service import VoyageReranker

    hits = [
        RetrievalHit(
            rank=1,
            chunk_id="a",
            doc_id="doc",
            title="A",
            document_number="1",
            legal_type="Luat",
            effect_status="Con hieu luc",
            section_path="Dieu 1",
            text="alpha",
            scores={"bm25": 1.0},
        ),
        RetrievalHit(
            rank=2,
            chunk_id="b",
            doc_id="doc",
            title="B",
            document_number="2",
            legal_type="Luat",
            effect_status="Con hieu luc",
            section_path="Dieu 2",
            text="beta",
            scores={"bm25": 0.5},
        ),
    ]
    client = Mock()
    client.rerank.return_value = SimpleNamespace(
        results=[
            SimpleNamespace(index=1, relevance_score=0.99),
            SimpleNamespace(index=0, relevance_score=0.12),
        ]
    )

    reranker = VoyageReranker(client=client, model="rerank-2.5", batch_size=4)
    reranked = reranker.rerank("query", hits, top_k=2)

    assert [hit.chunk_id for hit in reranked] == ["b", "a"]
    assert [hit.rank for hit in reranked] == [1, 2]
    assert reranked[0].scores["rerank"] == 0.99
    client.rerank.assert_called_once()
    assert client.rerank.call_args.kwargs["model"] == "rerank-2.5"
    assert client.rerank.call_args.kwargs["top_k"] == 2


def test_openai_compatible_answer_service_returns_model_answer_and_citations() -> None:
    from answer_service import OpenAICompatibleAnswerService
    from contracts import AnswerContext

    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Cau tra loi tu LLM.")
            )
        ]
    )
    service = OpenAICompatibleAnswerService(client=client, model="legal-model")

    result = service.answer(
        "Hoi gi?",
        [
            AnswerContext(
                source="retrieval",
                chunk_id="chunk-1",
                doc_id="doc-1",
                title="Van ban",
                text="Noi dung phap ly",
                citation="Van ban | Dieu 1",
            )
        ],
        temperature=0.2,
    )

    assert result["answer"] == "Cau tra loi tu LLM."
    assert result["citations"] == [
        {
            "chunk_id": "chunk-1",
            "doc_id": "doc-1",
            "title": "Van ban",
            "citation": "Van ban | Dieu 1",
        }
    ]
    request = client.chat.completions.create.call_args.kwargs
    assert request["model"] == "legal-model"
    assert request["temperature"] == 0.2
    assert "Noi dung phap ly" in request["messages"][-1]["content"]
