from __future__ import annotations

from contracts import RetrievalHit
from retrieval_modes import RetrievalRequest


class DemoRetrievalService:
    def search(self, request: RetrievalRequest) -> list[RetrievalHit]:
        return [
            RetrievalHit(
                rank=1,
                chunk_id="chunk:demo:000001",
                doc_id="demo",
                title="Van ban demo",
                document_number="01/2026/QH",
                legal_type="Luat",
                effect_status="Con hieu luc",
                section_path="Dieu 1",
                text="Noi dung demo cho cau hoi.",
                scores={"rrf": 0.03},
                citation="Van ban demo, Dieu 1",
            )
        ][: request.top_k]
