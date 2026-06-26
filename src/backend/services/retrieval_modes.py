from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RetrievalMode = Literal["dense", "sparse", "hybrid"]
ExecutionMode = Literal[
    "dense",
    "dense_rerank",
    "sparse",
    "sparse_rerank",
    "hybrid",
    "hybrid_rerank",
]

VALID_RETRIEVAL_MODES = {"dense", "sparse", "hybrid"}


def resolve_execution_mode(
    retrieval_mode: str,
    rerank_enabled: bool,
) -> ExecutionMode:
    if retrieval_mode not in VALID_RETRIEVAL_MODES:
        raise ValueError(
            "retrieval_mode must be one of: dense, sparse, hybrid"
        )
    if not rerank_enabled:
        return retrieval_mode  # type: ignore[return-value]
    return f"{retrieval_mode}_rerank"  # type: ignore[return-value]


@dataclass
class RerankConfig:
    enabled: bool = True
    model: str = "BAAI/bge-reranker-v2-m3"
    candidate_k: int = 50
    batch_size: int = 8
    device: str = "auto"
    timeout_ms: int = 30000

    def __post_init__(self) -> None:
        if self.candidate_k <= 0:
            raise ValueError("rerank.candidate_k must be positive")
        if self.batch_size <= 0:
            raise ValueError("rerank.batch_size must be positive")
        if self.timeout_ms <= 0:
            raise ValueError("rerank.timeout_ms must be positive")


@dataclass
class LLMConfig:
    temperature: float = 0.2
    max_context_chunks: int = 8

    def __post_init__(self) -> None:
        if not 0.0 <= self.temperature <= 1.0:
            raise ValueError("llm.temperature must be between 0.0 and 1.0")
        if self.max_context_chunks <= 0:
            raise ValueError("llm.max_context_chunks must be positive")


@dataclass
class GraphConfig:
    enabled: bool = True
    use_lightrag: bool = True
    max_hops: int = 1

    def __post_init__(self) -> None:
        if self.max_hops < 0:
            raise ValueError("graph.max_hops must be non-negative")


@dataclass
class RetrievalRequest:
    query: str
    retrieval_mode: RetrievalMode = "hybrid"
    rerank: RerankConfig | dict[str, Any] = field(default_factory=RerankConfig)
    top_k: int = 5
    filters: dict[str, Any] = field(default_factory=dict)
    llm: LLMConfig | dict[str, Any] = field(default_factory=LLMConfig)
    graph: GraphConfig | dict[str, Any] = field(default_factory=GraphConfig)
    include_trace: bool = True

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be empty")
        if self.retrieval_mode not in VALID_RETRIEVAL_MODES:
            raise ValueError(
                "retrieval_mode must be one of: dense, sparse, hybrid"
            )
        if isinstance(self.rerank, dict):
            self.rerank = RerankConfig(**self.rerank)
        if isinstance(self.llm, dict):
            self.llm = LLMConfig(**self.llm)
        if isinstance(self.graph, dict):
            self.graph = GraphConfig(**self.graph)
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if self.rerank.enabled and self.rerank.candidate_k < self.top_k:
            raise ValueError("rerank.candidate_k must be greater than or equal to top_k")

    @property
    def execution_mode(self) -> ExecutionMode:
        return resolve_execution_mode(
            self.retrieval_mode,
            self.rerank.enabled,
        )
