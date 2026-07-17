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


MAX_TOP_K = 50
MAX_CANDIDATE_K = 200
MAX_BATCH_SIZE = 64
MAX_TIMEOUT_MS = 120000
MAX_GRAPH_HOPS = 2
MAX_CONTEXT_CHUNKS = 32


@dataclass
class RerankConfig:
    enabled: bool = True
    provider: str | None = None
    model: str = "rerank-2.5"
    candidate_k: int = 50
    batch_size: int = 8
    device: str = "auto"
    timeout_ms: int = 30000

    def __post_init__(self) -> None:
        if not 0 < self.candidate_k <= MAX_CANDIDATE_K:
            raise ValueError(f"rerank.candidate_k must be between 1 and {MAX_CANDIDATE_K}")
        if not 0 < self.batch_size <= MAX_BATCH_SIZE:
            raise ValueError(f"rerank.batch_size must be between 1 and {MAX_BATCH_SIZE}")
        if not 0 < self.timeout_ms <= MAX_TIMEOUT_MS:
            raise ValueError(f"rerank.timeout_ms must be between 1 and {MAX_TIMEOUT_MS}")


@dataclass
class LLMConfig:
    temperature: float = 0.2
    max_context_chunks: int = 8
    max_tokens: int = 2048
    system_prompt: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.temperature <= 1.0:
            raise ValueError("llm.temperature must be between 0.0 and 1.0")
        if not 0 < self.max_context_chunks <= MAX_CONTEXT_CHUNKS:
            raise ValueError(f"llm.max_context_chunks must be between 1 and {MAX_CONTEXT_CHUNKS}")
        if self.max_tokens <= 0:
            raise ValueError("llm.max_tokens must be positive")


@dataclass
class GraphConfig:
    enabled: bool = True
    use_lightrag: bool = True
    max_hops: int = 1
    auto_depth: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.max_hops <= MAX_GRAPH_HOPS:
            raise ValueError(f"graph.max_hops must be between 0 and {MAX_GRAPH_HOPS}")


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
        if not 0 < self.top_k <= MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")
        if self.rerank.enabled and self.rerank.candidate_k < self.top_k:
            raise ValueError("rerank.candidate_k must be greater than or equal to top_k")

    @property
    def execution_mode(self) -> ExecutionMode:
        return resolve_execution_mode(
            self.retrieval_mode,
            self.rerank.enabled,
        )
