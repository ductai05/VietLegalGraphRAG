from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RerankConfigModel(BaseModel):
    enabled: bool = True
    model: str = "BAAI/bge-reranker-v2-m3"
    candidate_k: int = Field(default=50, gt=0)
    batch_size: int = Field(default=8, gt=0)
    device: str = "auto"
    timeout_ms: int = Field(default=30000, gt=0)


class LLMConfigModel(BaseModel):
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    max_context_chunks: int = Field(default=8, gt=0)


class GraphConfigModel(BaseModel):
    enabled: bool = True
    use_lightrag: bool = True
    max_hops: int = Field(default=1, ge=0)


class SearchRequestModel(BaseModel):
    query: str = Field(min_length=1)
    retrieval_mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    rerank: RerankConfigModel = Field(default_factory=RerankConfigModel)
    top_k: int = Field(default=5, gt=0)
    filters: dict[str, Any] = Field(default_factory=dict)
    graph: GraphConfigModel = Field(default_factory=GraphConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    include_trace: bool = True
