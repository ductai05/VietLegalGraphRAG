from __future__ import annotations

from typing import Any

from contracts import GraphContext, GraphEdge, GraphNode
from intent_detector import IntentDetector


class GraphRetriever:
    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database
        self.intent_detector = IntentDetector()

    def get_document_neighbors(
        self,
        doc_id: str,
        relations: list[str] | None = None,
        depth: int = 1,
    ) -> GraphContext:
        relation_filter = relations or ["AMENDS", "CITES", "REPEALS", "GUIDELINES"]
        with self.driver.session(database=self.database) as session:
            center_records = list(
                session.run(
                    "MATCH (d:Document) WHERE d.doc_id = $doc_id OR d.id = $node_id RETURN d",
                    doc_id=doc_id,
                    node_id=f"doc:{doc_id}",
                )
            )
            center = self._node_from_record(center_records[0]["d"]) if center_records else None
            edge_records = list(
                session.run(
                    """
                    MATCH (source:Document)-[rel]-(target:Document)
                    WHERE (source.doc_id = $doc_id OR source.id = $node_id OR target.doc_id = $doc_id OR target.id = $node_id)
                      AND type(rel) IN $relations
                    RETURN source, target, type(rel) AS type, rel.raw_label AS raw_label
                    LIMIT 100
                    """,
                    doc_id=doc_id,
                    node_id=f"doc:{doc_id}",
                    relations=relation_filter,
                    depth=depth,
                )
            )

        nodes_by_id: dict[str, GraphNode] = {}
        if center:
            nodes_by_id[center.id] = center
        edges: list[GraphEdge] = []
        center_id = center.id if center else f"doc:{doc_id}"
        for record in edge_records:
            source = self._node_from_record(record["source"])
            target = self._node_from_record(record["target"])
            nodes_by_id[source.id] = source
            nodes_by_id[target.id] = target
            direction = "out" if source.id == center_id else "in"
            edges.append(
                GraphEdge(
                    source=source.id,
                    target=target.id,
                    type=record["type"],
                    raw_label=record.get("raw_label") or "",
                    direction=direction,
                )
            )

        return GraphContext(
            center=center,
            nodes=list(nodes_by_id.values()),
            edges=edges,
            related_chunks=[],
            query_intent="general",
        )

    def retrieve(
        self,
        query: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext:
        detected = self.intent_detector.detect(query)
        doc_id = self._doc_id_from_hits(retrieval_hits)
        if not doc_id:
            return GraphContext(center=None, query_intent=detected["intent"] or "general")
        context = self.get_document_neighbors(doc_id, depth=max_hops)
        context.query_intent = detected["intent"] or "general"
        return context

    def _doc_id_from_hits(self, retrieval_hits: list[dict[str, Any]]) -> str | None:
        for hit in retrieval_hits:
            doc_id = hit.get("doc_id")
            if doc_id:
                return str(doc_id)
        return None

    def _node_from_record(self, value: Any) -> GraphNode:
        properties = dict(value)
        node_id = str(properties.get("id") or f"doc:{properties.get('doc_id', '')}")
        return GraphNode(id=node_id, label="Document", properties=properties)
