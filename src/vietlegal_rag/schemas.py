from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator


class OcrPageModel(BaseModel):
    page_num: int
    text: str


class OcrResponseModel(BaseModel):
    success: bool
    text: str
    pages: list[OcrPageModel] = Field(default_factory=list)
    provider: str
    warnings: list[str] = Field(default_factory=list)


class RerankConfigModel(BaseModel):
    enabled: bool = True
    provider: Literal["voyage", "jina", "noop"] | None = None
    model: str = "rerank-2.5"
    candidate_k: int = Field(default=50, gt=0, le=200)
    batch_size: int = Field(default=8, gt=0, le=64)
    device: str = "auto"
    timeout_ms: int = Field(default=30000, gt=0, le=120000)


class LLMConfigModel(BaseModel):
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    max_context_chunks: int = Field(default=8, gt=0, le=32)


class GraphConfigModel(BaseModel):
    enabled: bool = True
    use_lightrag: bool = True
    max_hops: int = Field(default=1, ge=0, le=2)
    auto_depth: bool = True


class SearchRequestModel(BaseModel):
    query: str = Field(min_length=1)
    retrieval_mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    rerank: RerankConfigModel = Field(default_factory=RerankConfigModel)
    top_k: int = Field(default=5, gt=0, le=50)
    filters: dict[str, Any] = Field(default_factory=dict)
    graph: GraphConfigModel = Field(default_factory=GraphConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    include_trace: bool = Field(
        default=True,
        description=(
            "Reserved for forward compatibility. "
            "MVP always includes retrieval_trace in the /answer response. "
            "Frontend MUST expect retrieval_trace to be present."
        ),
    )

    @model_validator(mode="after")
    def validate_candidate_k_envelope(self) -> Self:
        if self.rerank.enabled and self.rerank.candidate_k < self.top_k:
            raise ValueError("rerank.candidate_k must be greater than or equal to top_k")
        return self


def build_search_request(
    query: str,
    retrieval_mode: str,
    top_k: int,
    rerank_enabled: bool,
    rerank_model: str,
    graph_enabled: bool,
    max_hops: int,
    llm_temperature: float,
    max_context_chunks: int,
) -> SearchRequestModel:
    # Ensure candidate_k is >= top_k to avoid validation error
    candidate_k = max(top_k * 4, 20)
    if candidate_k < top_k:
        candidate_k = top_k
        
    return SearchRequestModel(
        query=query,
        retrieval_mode=retrieval_mode,
        top_k=top_k,
        rerank=RerankConfigModel(
            enabled=rerank_enabled,
            model=rerank_model,
            candidate_k=candidate_k,
        ),
        graph=GraphConfigModel(
            enabled=graph_enabled,
            max_hops=max_hops,
        ),
        llm=LLMConfigModel(
            temperature=llm_temperature,
            max_context_chunks=max_context_chunks,
        ),
    )

