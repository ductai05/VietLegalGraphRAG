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
