from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from embedding_service import (  # noqa: E402
    KNOWN_EMBEDDING_DIMS,
    OpenAICompatibleEmbedder,
    VoyageEmbedder,
)


# --- VoyageEmbedder ---


def test_voyage_embedder_calls_sdk_with_query_input_type() -> None:
    client = Mock()
    client.embed.return_value = SimpleNamespace(embeddings=[[0.1, 0.2, 0.3]])
    embedder = VoyageEmbedder(client, model="voyage-3.5")

    vector = embedder.embed_query("hop dong lao dong")

    client.embed.assert_called_once_with(
        ["hop dong lao dong"],
        model="voyage-3.5",
        input_type="query",
    )
    assert vector == [0.1, 0.2, 0.3]
    assert all(isinstance(value, float) for value in vector)


def test_voyage_embedder_raises_on_empty_embeddings() -> None:
    client = Mock()
    client.embed.return_value = SimpleNamespace(embeddings=[])
    embedder = VoyageEmbedder(client, model="voyage-3.5")

    with pytest.raises(RuntimeError, match="no embeddings"):
        embedder.embed_query("q")


def test_voyage_embedder_infers_known_dims() -> None:
    embedder = VoyageEmbedder(Mock(), model="voyage-3.5")
    assert embedder.dims == KNOWN_EMBEDDING_DIMS["voyage-3.5"] == 1024


def test_voyage_embedder_explicit_dims_override() -> None:
    embedder = VoyageEmbedder(Mock(), model="voyage-3.5", dims=512)
    assert embedder.dims == 512


def test_voyage_embedder_unknown_model_has_no_dims() -> None:
    embedder = VoyageEmbedder(Mock(), model="future-model")
    assert embedder.dims is None


# --- OpenAICompatibleEmbedder ---


def test_openai_embedder_calls_embeddings_create() -> None:
    client = Mock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.5, 0.6])]
    )
    embedder = OpenAICompatibleEmbedder(client, model="text-embedding-3-small")

    vector = embedder.embed_query("thue thu nhap")

    client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small",
        input=["thue thu nhap"],
    )
    assert vector == [0.5, 0.6]


def test_openai_embedder_accepts_dict_payloads() -> None:
    client = Mock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[{"embedding": [1.0, 2.0]}]
    )
    embedder = OpenAICompatibleEmbedder(client, model="text-embedding-3-small")
    assert embedder.embed_query("q") == [1.0, 2.0]


def test_openai_embedder_raises_on_empty_data() -> None:
    client = Mock()
    client.embeddings.create.return_value = SimpleNamespace(data=[])
    embedder = OpenAICompatibleEmbedder(client, model="text-embedding-3-small")
    with pytest.raises(RuntimeError, match="no data"):
        embedder.embed_query("q")


def test_openai_embedder_infers_known_dims() -> None:
    embedder = OpenAICompatibleEmbedder(Mock(), model="text-embedding-3-large")
    assert embedder.dims == 3072
