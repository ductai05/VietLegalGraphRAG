"""Query-embedding providers for dense (kNN) retrieval.

Providers reuse SDKs already in the dependency set (voyageai, openai).
No new dependencies. Absence of an embedder (provider "none") means dense
retrieval is disabled and the runtime serves BM25-only.
"""

from __future__ import annotations

from typing import Any, Protocol

# Dims for models we recognize; used for the startup mapping check when
# EMBEDDING_DIMS is not set explicitly. Unknown models skip the check.
KNOWN_EMBEDDING_DIMS: dict[str, int] = {
    "voyage-3": 1024,
    "voyage-3.5": 1024,
    "voyage-3.5-lite": 1024,
    "voyage-3-large": 1024,
    "voyage-context-3": 1024,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


class Embedder(Protocol):
    model: str
    dims: int | None

    def embed_query(self, text: str) -> list[float]:
        ...


class VoyageEmbedder:
    """Voyage AI embeddings via the voyageai SDK client."""

    def __init__(self, client: Any, model: str, dims: int | None = None) -> None:
        self.client = client
        self.model = model
        self.dims = dims or KNOWN_EMBEDDING_DIMS.get(model)

    def embed_query(self, text: str) -> list[float]:
        result = self.client.embed(
            [text],
            model=self.model,
            input_type="query",
        )
        embeddings = getattr(result, "embeddings", None)
        if not embeddings:
            raise RuntimeError("voyage embed returned no embeddings")
        return [float(value) for value in embeddings[0]]


class OpenAICompatibleEmbedder:
    """Embeddings via any OpenAI-compatible /embeddings endpoint."""

    def __init__(self, client: Any, model: str, dims: int | None = None) -> None:
        self.client = client
        self.model = model
        self.dims = dims or KNOWN_EMBEDDING_DIMS.get(model)

    def embed_query(self, text: str) -> list[float]:
        response = self.client.embeddings.create(model=self.model, input=[text])
        data = getattr(response, "data", None)
        if not data:
            raise RuntimeError("embeddings endpoint returned no data")
        embedding = getattr(data[0], "embedding", None)
        if embedding is None and isinstance(data[0], dict):
            embedding = data[0].get("embedding")
        if not embedding:
            raise RuntimeError("embeddings endpoint returned empty embedding")
        return [float(value) for value in embedding]
