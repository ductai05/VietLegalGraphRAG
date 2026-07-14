from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND_APP = ROOT / "src" / "backend" / "app"
BACKEND_SERVICES = ROOT / "src" / "backend" / "services"
for path in (BACKEND_APP, BACKEND_SERVICES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from embedding_service import (  # noqa: E402
    DEFAULT_HF_EMBEDDING_DIMS,
    DEFAULT_HF_EMBEDDING_MODEL,
    QUERY_PREFIX,
    LocalHFEmbedder,
)


class FakeEncoder:
    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self.vectors = [[0.1, 0.2, 0.3]] if vectors is None else vectors
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return self.vectors


def test_local_hf_embedder_uses_vnlegal_model_and_1024_dims_by_default() -> None:
    embedder = LocalHFEmbedder(encoder=FakeEncoder())

    assert embedder.model == DEFAULT_HF_EMBEDDING_MODEL == "darklethelong/vnlegal-lal"
    assert embedder.dims == DEFAULT_HF_EMBEDDING_DIMS == 1024


def test_local_hf_embedder_adds_pipeline_query_prefix_before_encoding() -> None:
    encoder = FakeEncoder(vectors=[[1, "2.5", 3.0]])  # type: ignore[list-item]
    embedder = LocalHFEmbedder(encoder=encoder)

    vector = embedder.embed_query("điều kiện cấp giấy phép xây dựng")

    assert encoder.calls == [
        [QUERY_PREFIX + "điều kiện cấp giấy phép xây dựng"]
    ]
    assert vector == [1.0, 2.5, 3.0]


def test_local_hf_embedder_raises_on_empty_encoder_response() -> None:
    embedder = LocalHFEmbedder(encoder=FakeEncoder(vectors=[]))

    with pytest.raises(RuntimeError, match="no embeddings"):
        embedder.embed_query("q")
