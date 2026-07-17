from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ContextSource = Literal["retrieval", "graph"]


@dataclass
class AnswerContext:
    source: ContextSource
    chunk_id: str | None
    doc_id: str
    title: str
    text: str
    citation: str
    relation: str | None = None
    raw_label: str | None = None
    effect_status: str = ""
    resolution: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalHit:
    rank: int
    chunk_id: str
    doc_id: str
    title: str
    document_number: str
    legal_type: str
    effect_status: str
    section_path: str
    text: str
    scores: dict[str, float] = field(default_factory=dict)
    citation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_answer_context(self) -> AnswerContext:
        return AnswerContext(
            source="retrieval",
            chunk_id=self.chunk_id,
            doc_id=self.doc_id,
            title=self.title,
            text=self.text,
            citation=self.citation,
            effect_status=self.effect_status,
        )


@dataclass
class GraphNode:
    id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str
    raw_label: str
    direction: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphContext:
    center: GraphNode | None
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    related_chunks: list[AnswerContext] = field(default_factory=list)
    query_intent: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "center": self.center.to_dict() if self.center else None,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "related_chunks": [chunk.to_dict() for chunk in self.related_chunks],
            "query_intent": self.query_intent,
        }


@dataclass
class ServiceWarning:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
