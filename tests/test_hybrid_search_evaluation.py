# ruff: noqa: E402
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "pipeline" / "05_evaluation"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

pytest.importorskip("elasticsearch")

from hybrid_search import (
    DEFAULT_HYBRID_QUERY,
    DEFAULT_RERANKER_MODEL,
    fuse_ranked_hits,
    parse_args,
)
from run_pipeline_eval import parse_args as parse_pipeline_eval_args


def test_fuse_ranked_hits_uses_one_based_rrf_and_preserves_component_scores() -> None:
    dense_hits = [
        {"chunk_id": "dense-only", "score": 0.9, "rank": 1, "payload": {"title": "D"}},
        {"chunk_id": "shared", "score": 0.8, "rank": 2, "payload": {"title": "DS"}},
    ]
    sparse_hits = [
        {"chunk_id": "shared", "score": 12.0, "rank": 1, "payload": {"chunk_text": "S"}},
        {"chunk_id": "sparse-only", "score": 9.0, "rank": 2, "payload": {"title": "S"}},
    ]

    candidates = fuse_ranked_hits(
        dense_hits,
        sparse_hits,
        candidate_k=3,
        rrf_k=60,
    )

    assert [hit["chunk_id"] for hit in candidates] == [
        "shared",
        "dense-only",
        "sparse-only",
    ]
    assert candidates[0]["score"] == (1.0 / 62.0) + (1.0 / 61.0)
    assert candidates[0]["dense_score"] == 0.8
    assert candidates[0]["sparse_score"] == 12.0
    assert candidates[0]["retrieval_sources"] == ["dense", "sparse"]


def test_parse_args_loads_env_file_and_single_hybrid_index(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "production.env"
    env_file.write_text(
        "\n".join(
            [
                "ELASTICSEARCH_URL=https://elastic.example",
                "ELASTICSEARCH_API_KEY=secret",
                "ELASTICSEARCH_ALIAS=vietlegal_chunks",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ELASTICSEARCH_URL", raising=False)
    monkeypatch.delenv("ELASTICSEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ELASTICSEARCH_ALIAS", raising=False)

    args = parse_args(
        [
            "--env-file",
            str(env_file),
            "--index",
            "vietlegal_chunks",
            "--query",
            "thủ tục cấp giấy phép xây dựng",
        ]
    )

    assert args.url == "https://elastic.example"
    assert args.api_key == "secret"
    assert args.dense_index == "vietlegal_chunks"
    assert args.sparse_index == "vietlegal_chunks"
    assert args.reranker_model == DEFAULT_RERANKER_MODEL


def test_parse_args_uses_default_smoke_query_when_no_mode_is_provided(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = tmp_path / "production.env"
    env_file.write_text(
        "\n".join(
            [
                "ELASTICSEARCH_URL=https://elastic.example",
                "ELASTICSEARCH_API_KEY=secret",
                "ELASTICSEARCH_INDEX=vietlegal_chunks_hybrid_v1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ELASTICSEARCH_URL", raising=False)
    monkeypatch.delenv("ELASTICSEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ELASTICSEARCH_ALIAS", raising=False)
    monkeypatch.delenv("ELASTICSEARCH_INDEX", raising=False)

    args = parse_args(["--env-file", str(env_file)])

    assert args.query == DEFAULT_HYBRID_QUERY
    assert args.gold is None
    assert args.dense_index == "vietlegal_chunks_hybrid_v1"
    assert args.sparse_index == "vietlegal_chunks_hybrid_v1"


def test_pipeline_eval_runner_loads_hybrid_index_and_reranker_defaults(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = tmp_path / "production.env"
    env_file.write_text(
        "\n".join(
            [
                "ELASTICSEARCH_URL=https://elastic.example",
                "ELASTICSEARCH_API_KEY=secret",
                "ELASTICSEARCH_ALIAS=vietlegal_chunks",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ELASTICSEARCH_URL", raising=False)
    monkeypatch.delenv("ELASTICSEARCH_API_KEY", raising=False)
    monkeypatch.delenv("ELASTICSEARCH_ALIAS", raising=False)

    args = parse_pipeline_eval_args(["--env-file", str(env_file)])

    assert args.url == "https://elastic.example"
    assert args.api_key == "secret"
    assert args.index == "vietlegal_chunks"
    assert args.rrf_k == 60
    assert args.reranker_model == DEFAULT_RERANKER_MODEL
