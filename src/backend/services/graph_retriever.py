from __future__ import annotations

from collections.abc import Callable
from typing import Any

from contracts import AnswerContext, GraphContext, GraphEdge, GraphNode
from intent_detector import IntentDetector

# Relationship types this backend supports. Unrecognised types are silently
# excluded at query time; schema migrations will add validation later.
SUPPORTED_RELATIONS = frozenset({
    "AMENDS",
    "CITES",
    "REPEALS",
    "GUIDELINES",
    "RELATED_TO",
    "VERSION_OF",
    "REPLACED_BY",
})

# Hard cap on traversal depth matching the Neo4j BOLT protocol maximum.
MAX_DEPTH = 10
RelatedDocument = dict[str, str]
ChunkFetcher = Callable[[str, list[RelatedDocument]], list[AnswerContext]]


class GraphRetriever:
    def __init__(
        self,
        driver: Any,
        database: str = "neo4j",
        chunk_fetcher: ChunkFetcher | None = None,
        related_doc_limit: int = 3,
    ) -> None:
        self.driver = driver
        self.database = database
        self.intent_detector = IntentDetector()
        self.chunk_fetcher = chunk_fetcher
        self.related_doc_limit = max(0, related_doc_limit)

    def get_document_neighbors(
        self,
        doc_id: str,
        relations: list[str] | None = None,
        depth: int = 1,
    ) -> GraphContext:
        """Traverse document graph outward `depth` hops.

        `depth` is clamped to [1, MAX_DEPTH]. When depth > 1 the query uses
        a variable-length path pattern so relationships are followed
        across multiple hops.
        """
        # Clamp depth to protocol maximum; guard against negative/zero input.
        depth = max(1, min(depth, MAX_DEPTH))

        relation_filter = self._filter_relations(relations)

        node_id = f"doc:{doc_id}"
        try:
            with self.driver.session(database=self.database) as session:
                center = self._find_center(session, doc_id, node_id)
                edge_records = self._traverse_edges(
                    session, doc_id, node_id, relation_filter, depth
                )
                return self._build_context(center, edge_records, node_id, doc_id)
        except Exception:
            # Do not expose Neo4j internals to clients; return empty context.
            return GraphContext(
                center=None,
                nodes=[],
                edges=[],
                related_chunks=[],
                query_intent="general",
            )

    def get_version_chain(self, doc_id: str) -> list[dict[str, Any]]:
        """Return chronological version chain for a document via VERSION_OF/REPLACED_BY.

        Returns oldest→newest list of {doc_id, title, document_number, status, version_order}.
        Silently returns [] when the graph is unavailable or no version data exists.
        """
        node_id = f"doc:{doc_id}"
        try:
            with self.driver.session(database=self.database) as session:
                if not self._has_any_version_relation(session):
                    return []
                records = list(
                    session.run(
                        """
                        MATCH path = (root)-[:VERSION_OF|REPLACED_BY*]->(current)-[:VERSION_OF|REPLACED_BY*]->(leaf)
                        WHERE current.doc_id = $doc_id OR current.id = $node_id
                           OR root.doc_id = $doc_id OR root.id = $node_id
                           OR leaf.doc_id = $doc_id OR leaf.id = $node_id
                        UNWIND NODES(path) AS n
                        WITH n
                        ORDER BY COALESCE(n.issuance_date, n.effect_date, '') ASC
                        WITH COLLECT(DISTINCT n) AS chain
                        UNWIND chain AS node
                        RETURN node.doc_id AS doc_id,
                               node.id AS node_id,
                               node.title AS title,
                               node.document_number AS document_number,
                               node.effect_status AS status,
                               node.issuance_date AS issuance_date
                        """,
                        doc_id=doc_id,
                        node_id=node_id,
                    )
                )
                return [
                    {
                        "doc_id": self._public_doc_id(
                            {"doc_id": r["doc_id"], "id": r["node_id"]}
                        ) or node_id,
                        "title": str(r["title"]) if r["title"] else "",
                        "document_number": str(r["document_number"]) if r["document_number"] else "",
                        "status": str(r["status"]) if r["status"] else "",
                        "version_order": i,
                    }
                    for i, r in enumerate(records)
                ]
        except Exception:
            return []

    def _has_any_version_relation(self, session: Any) -> bool:
        records = list(
            session.run(
                "CALL db.relationshipTypes() YIELD relationshipType "
                "RETURN collect(relationshipType) AS types"
            )
        )
        if not records:
            return True
        types = self._record_value(records[0], "types")
        if types is None:
            return True
        return bool({"VERSION_OF", "REPLACED_BY"} & set(types))

    def retrieve(
        self,
        query: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext:
        detected = self.intent_detector.detect(query)
        intent = detected["intent"] or "general"
        doc_ids = self._doc_ids_from_hits(
            retrieval_hits,
            document_number=detected.get("document_number"),
        )
        if not doc_ids:
            return GraphContext(center=None, query_intent=intent)

        fallback_context: GraphContext | None = None
        for doc_id in doc_ids:
            context = self.get_document_neighbors(doc_id, depth=max_hops)
            context.query_intent = intent
            if fallback_context is None:
                fallback_context = context

            if self.chunk_fetcher is not None:
                related_documents = self._related_documents(
                    context,
                    source_doc_id=doc_id,
                    intent=context.query_intent,
                )
                if related_documents:
                    try:
                        context.related_chunks = self.chunk_fetcher(query, related_documents)
                    except Exception:
                        context.related_chunks = []

            if context.related_chunks or context.edges:
                return context

        return fallback_context or GraphContext(center=None, query_intent=intent)

    def retrieve_chunk_context(
        self,
        doc_id: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext:
        """Retrieve graph context for a specific doc and attach related chunks."""
        context = self.get_document_neighbors(doc_id, depth=max_hops)
        query = ""
        if retrieval_hits:
            first_hit = retrieval_hits[0]
            query = str(first_hit.get("text") or first_hit.get("query") or "")
        if self.chunk_fetcher is None:
            return context
        related_documents = self._related_documents(
            context,
            source_doc_id=doc_id,
            intent=context.query_intent,
        )
        if not related_documents:
            return context
        try:
            context.related_chunks = self.chunk_fetcher(query, related_documents)
        except Exception:
            context.related_chunks = []
        return context

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filter_relations(self, relations: list[str] | None) -> list[str]:
        """Intersect caller-supplied relations with supported types."""
        if not relations:
            base = SUPPORTED_RELATIONS
        else:
            base = frozenset(r.upper() for r in relations)
        return sorted(base & SUPPORTED_RELATIONS)

    def _find_center(
        self,
        session: Any,
        doc_id: str,
        node_id: str,
    ) -> GraphNode | None:
        records = list(
            session.run(
                "MATCH (d:Document) WHERE d.doc_id = $doc_id OR d.id = $node_id RETURN d LIMIT 1",
                doc_id=doc_id,
                node_id=node_id,
            )
        )
        if not records:
            return None
        return self._node_from_record(self._record_value(records[0], "d"))

    def _traverse_edges(
        self,
        session: Any,
        doc_id: str,
        node_id: str,
        relation_filter: list[str],
        depth: int,
    ) -> list[Any]:
        """Execute depth-bounded traversal. Single-hop when depth==1."""
        if depth == 1:
            query = """
                MATCH (source:Document)-[rel]-(target:Document)
                WHERE (source.doc_id = $doc_id OR source.id = $node_id
                    OR target.doc_id = $doc_id OR target.id = $node_id)
                  AND type(rel) IN $relations
                RETURN source, target, type(rel) AS type,
                       rel.raw_label AS raw_label
                LIMIT 100
            """
            records = list(
                session.run(
                    query,
                    doc_id=doc_id,
                    node_id=node_id,
                    relations=relation_filter,
                )
            )
        else:
            # Variable-length path, follows relationships up to `depth` hops.
            # Paths that exceed 100 intermediate nodes are discarded to avoid
            # unbounded traversals on highly-connected nodes.
            query = """
                MATCH path = (start:Document)-[rel*1..%d]-(end:Document)
                WHERE (start.doc_id = $doc_id OR start.id = $node_id)
                WITH NODES(path) AS ns, RELS(path) AS rs
                UNWIND RANGE(0, SIZE(ns) - 2) AS i
                WITH ns[i] AS source, ns[i + 1] AS target, rs[i] AS rel
                WHERE type(rel) IN $relations
                RETURN source, target, type(rel) AS type,
                       rel.raw_label AS raw_label
                LIMIT 100
            """ % depth
            records = list(
                session.run(
                    query,
                    doc_id=doc_id,
                    node_id=node_id,
                    relations=relation_filter,
                )
            )
        return records

    def _build_context(
        self,
        center: GraphNode | None,
        edge_records: list[Any],
        center_id: str,
        doc_id: str,
    ) -> GraphContext:
        nodes_by_id: dict[str, GraphNode] = {}
        if center:
            nodes_by_id[center.id] = center
        edges: list[GraphEdge] = []
        resolved_center_id = center.id if center else center_id
        for record in edge_records:
            source = self._node_from_record(self._record_value(record, "source"))
            target = self._node_from_record(self._record_value(record, "target"))
            nodes_by_id[source.id] = source
            nodes_by_id[target.id] = target
            direction = "out" if source.id == resolved_center_id else "in"
            edges.append(
                GraphEdge(
                    source=source.id,
                    target=target.id,
                    type=str(self._record_value(record, "type") or ""),
                    raw_label=str(self._record_value(record, "raw_label") or ""),
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

    def _doc_id_from_hits(
        self,
        retrieval_hits: list[dict[str, Any]],
        document_number: str | None = None,
    ) -> str | None:
        doc_ids = self._doc_ids_from_hits(retrieval_hits, document_number)
        return doc_ids[0] if doc_ids else None

    def _doc_ids_from_hits(
        self,
        retrieval_hits: list[dict[str, Any]],
        document_number: str | None = None,
    ) -> list[str]:
        doc_ids: list[str] = []
        seen: set[str] = set()

        def append_doc_id(value: Any) -> None:
            doc_id = self._normalize_doc_id(str(value or ""))
            if not doc_id or doc_id in seen:
                return
            seen.add(doc_id)
            doc_ids.append(doc_id)

        if document_number:
            expected = document_number.strip().casefold()
            for hit in retrieval_hits:
                candidate = str(hit.get("document_number") or "").strip().casefold()
                if candidate == expected and hit.get("doc_id"):
                    append_doc_id(hit["doc_id"])
        for hit in retrieval_hits:
            append_doc_id(hit.get("doc_id"))
        return doc_ids

    def _related_documents(
        self,
        context: GraphContext,
        source_doc_id: str,
        intent: str,
    ) -> list[RelatedDocument]:
        if not context.center:
            return []
        node_by_id = {node.id: node for node in context.nodes}
        priority = self._relation_priority(intent)
        candidates: list[tuple[int, int, RelatedDocument]] = []
        seen: set[str] = set()
        source_key = self._normalize_doc_id(source_doc_id)
        for order, edge in enumerate(context.edges):
            if edge.source == context.center.id:
                neighbor_id = edge.target
            elif edge.target == context.center.id:
                neighbor_id = edge.source
            else:
                continue
            neighbor = node_by_id.get(neighbor_id)
            if neighbor is None:
                continue
            doc_id = self._public_doc_id(neighbor.properties)
            doc_key = self._normalize_doc_id(doc_id)
            if not doc_id or doc_key == source_key or doc_key in seen:
                continue
            seen.add(doc_key)
            candidates.append(
                (
                    priority.get(edge.type, len(priority) + 100),
                    order,
                    {
                        "doc_id": doc_id,
                        "relation": edge.type,
                        "raw_label": edge.raw_label,
                    },
                )
            )
        candidates.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in candidates[: self.related_doc_limit]]

    def _relation_priority(self, intent: str) -> dict[str, int]:
        orders = {
            "citation": ["CITES", "GUIDELINES", "RELATED_TO"],
            "amendment": ["AMENDS", "REPLACED_BY", "VERSION_OF", "RELATED_TO"],
            "repeal": ["REPEALS", "REPLACED_BY", "VERSION_OF", "RELATED_TO"],
            "guideline": ["GUIDELINES", "CITES", "RELATED_TO"],
            "general": ["CITES", "AMENDS", "REPEALS", "GUIDELINES", "RELATED_TO"],
        }
        selected = orders.get(intent, orders["general"])
        return {relation: index for index, relation in enumerate(selected)}

    def _public_doc_id(self, properties: dict[str, Any]) -> str:
        doc_id = str(properties.get("doc_id") or "").strip()
        if doc_id:
            return self._normalize_doc_id(doc_id)
        node_id = str(properties.get("id") or "").strip()
        return self._normalize_doc_id(node_id)

    @staticmethod
    def _normalize_doc_id(value: str) -> str:
        stripped = str(value or "").strip()
        if stripped.startswith("doc:"):
            return stripped[4:]
        return stripped

    def _node_from_record(self, value: Any) -> GraphNode:
        properties = self._node_properties(value)
        node_id = str(properties.get("id") or f"doc:{properties.get('doc_id', '')}")
        return GraphNode(id=node_id, label="Document", properties=properties)

    def _node_properties(self, value: Any) -> dict[str, Any]:
        try:
            return dict(value)
        except Exception:
            properties: dict[str, Any] = {}
            for key in (
                "id",
                "doc_id",
                "title",
                "document_number",
                "effect_status",
                "issuance_date",
                "effect_date",
            ):
                item = self._record_value(value, key)
                if item is not None:
                    properties[key] = item
            return properties

    def _record_value(self, record: Any, key: str) -> Any:
        if record is None:
            return None
        try:
            return record[key]
        except Exception:
            pass
        if isinstance(record, dict):
            return record.get(key)
        getter = getattr(record, "__getitem__", None)
        if callable(getter):
            try:
                return getter(key)
            except TypeError:
                try:
                    return getter(record, key)
                except Exception:
                    return None
            except Exception:
                return None
        return getattr(record, key, None)
