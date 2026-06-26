from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from schema import (
    CHUNK_FIELDS,
    DOCUMENT_FIELDS,
    EDGE_FIELDS,
    NODE_FIELDS,
    clean_text,
    is_present,
    join_list,
    normalize_relationship_label,
    priority_tier,
    slugify,
    split_multi_value,
)


@dataclass
class GraphTables:
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    document_relationship_edges: List[Dict[str, Any]] = field(default_factory=list)
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    chunk_edges: List[Dict[str, Any]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


class GraphBuilder:
    def __init__(self) -> None:
        self.nodes_by_id: Dict[str, Dict[str, Any]] = {}
        self.edges_by_id: Dict[str, Dict[str, Any]] = {}
        self.documents: List[Dict[str, Any]] = []
        self.document_relationship_edges: List[Dict[str, Any]] = []
        self.chunks: List[Dict[str, Any]] = []
        self.chunk_edges: List[Dict[str, Any]] = []
        self.document_ids: set[str] = set()
        self.chunk_ids: set[str] = set()
        self.duplicate_node_ids = 0
        self.duplicate_edge_ids = 0
        self.orphan_document_relationship_edges = 0
        self.self_loop_document_relationship_edges = 0
        self.orphan_chunk_rows = 0
        self.raw_relationship_counts: Dict[str, int] = {}
        self.edge_type_counts: Dict[str, int] = {}

    def build(
        self,
        metadata_rows: Iterable[Dict[str, Any]],
        relationship_rows: Iterable[Dict[str, Any]],
        chunk_rows: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> GraphTables:
        for row in metadata_rows:
            self._add_document(row)

        for row in relationship_rows:
            self._add_document_relationship(row)

        if chunk_rows is not None:
            for row in chunk_rows:
                self._add_chunk(row)
            self._add_parent_chunk_edges()

        return GraphTables(
            nodes=list(self.nodes_by_id.values()),
            edges=list(self.edges_by_id.values()),
            documents=self.documents,
            document_relationship_edges=self.document_relationship_edges,
            chunks=self.chunks,
            chunk_edges=self.chunk_edges,
            summary=self._summary(),
        )

    def _add_document(self, row: Dict[str, Any]) -> None:
        doc_id_raw = row.get("id")
        if doc_id_raw is None:
            return
        doc_node_id = document_node_id(doc_id_raw)
        self.document_ids.add(doc_node_id)

        sectors = split_multi_value(row.get("legal_sectors"))
        document = {
            "id": doc_node_id,
            "doc_id": clean_text(doc_id_raw),
            "document_number": clean_text(row.get("document_number")),
            "title": clean_text(row.get("title")),
            "legal_type": clean_text(row.get("legal_type")),
            "legal_sectors": clean_text(row.get("legal_sectors")),
            "sector_list": "|".join(sectors),
            "issuing_authority": clean_text(row.get("issuing_authority")),
            "issuance_date": clean_text(row.get("issuance_date")),
            "effect_date": clean_text(row.get("effect_date")),
            "effectless_date": clean_text(row.get("effectless_date")),
            "effect_status": clean_text(row.get("effect_status")),
            "signers": clean_text(row.get("signers")),
            "source": clean_text(row.get("source")),
            "priority_tier": priority_tier(row.get("legal_type")),
        }
        self.documents.append(document)
        self._add_node(
            node_id=doc_node_id,
            label="Document",
            name=document["title"] or document["document_number"] or doc_node_id,
            source_id=document["doc_id"],
            properties=document,
        )

        if is_present(row.get("legal_type")):
            legal_type_id = f"legal_type:{slugify(row.get('legal_type'))}"
            self._add_node(legal_type_id, "LegalType", clean_text(row.get("legal_type")))
            self._add_edge(doc_node_id, legal_type_id, "HAS_LEGAL_TYPE")

        if is_present(row.get("issuing_authority")):
            authority_id = f"authority:{slugify(row.get('issuing_authority'))}"
            self._add_node(authority_id, "Authority", clean_text(row.get("issuing_authority")))
            self._add_edge(doc_node_id, authority_id, "ISSUED_BY")

        for sector in sectors:
            sector_id = f"sector:{slugify(sector)}"
            self._add_node(sector_id, "Sector", sector)
            self._add_edge(doc_node_id, sector_id, "IN_SECTOR")

    def _add_document_relationship(self, row: Dict[str, Any]) -> None:
        source_id = document_node_id(row.get("doc_id"))
        target_id = document_node_id(row.get("other_doc_id"))
        normalized = normalize_relationship_label(row.get("relationship"))
        raw_label = normalized.raw_label
        self.raw_relationship_counts[raw_label] = self.raw_relationship_counts.get(raw_label, 0) + 1

        if source_id not in self.document_ids or target_id not in self.document_ids:
            self.orphan_document_relationship_edges += 1
            return
        if source_id == target_id:
            self.self_loop_document_relationship_edges += 1
            return
        if normalized.reverse_direction:
            source_id, target_id = target_id, source_id

        edge = self._add_edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=normalized.edge_type,
            raw_type=raw_label,
            properties={"raw_relationship": raw_label},
        )
        if edge is not None:
            self.document_relationship_edges.append(edge)

    def _add_chunk(self, row: Dict[str, Any]) -> None:
        chunk_id_raw = clean_text(row.get("chunk_id"))
        doc_id_raw = row.get("doc_id")
        if not chunk_id_raw or doc_id_raw is None:
            self.orphan_chunk_rows += 1
            return

        doc_id = document_node_id(doc_id_raw)
        if doc_id not in self.document_ids:
            self.orphan_chunk_rows += 1
            return

        node_id = chunk_node_id(chunk_id_raw)
        section_path = join_list(row.get("section_path"))
        quality_flags = join_list(row.get("quality_flags"))
        chunk = {
            "id": node_id,
            "chunk_id": chunk_id_raw,
            "doc_id": clean_text(doc_id_raw),
            "chunk_type": clean_text(row.get("chunk_type")),
            "section_path": section_path,
            "procedure_name": clean_text(row.get("procedure_name")),
            "embed": bool(row.get("embed")),
            "keyword_index": bool(row.get("keyword_index")),
            "parent_id": clean_text(row.get("parent_id")),
            "prev_chunk_id": clean_text(row.get("prev_chunk_id")),
            "next_chunk_id": clean_text(row.get("next_chunk_id")),
            "token_estimate": clean_text(row.get("token_estimate")),
            "quality_flags": quality_flags,
        }
        self.chunks.append(chunk)
        self.chunk_ids.add(node_id)
        self._add_node(
            node_id=node_id,
            label="Chunk",
            name=section_path or chunk_id_raw,
            source_id=chunk_id_raw,
            properties=chunk,
        )
        has_chunk = self._add_edge(doc_id, node_id, "HAS_CHUNK")
        if has_chunk is not None:
            self.chunk_edges.append(has_chunk)

        next_id = chunk.get("next_chunk_id")
        if next_id:
            next_node_id = chunk_node_id(next_id)
            next_edge = self._add_edge(node_id, next_node_id, "NEXT_CHUNK")
            if next_edge is not None:
                self.chunk_edges.append(next_edge)

    def _add_parent_chunk_edges(self) -> None:
        for chunk in self.chunks:
            parent_id = chunk.get("parent_id")
            if not parent_id:
                continue
            parent_node_id = chunk_node_id(parent_id)
            child_node_id = chunk["id"]
            if parent_node_id not in self.chunk_ids or parent_node_id == child_node_id:
                continue
            edge = self._add_edge(parent_node_id, child_node_id, "PARENT_OF")
            if edge is not None:
                self.chunk_edges.append(edge)

    def _add_node(
        self,
        node_id: str,
        label: str,
        name: str,
        source_id: str = "",
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        if node_id in self.nodes_by_id:
            if self.nodes_by_id[node_id]["label"] != label:
                self.duplicate_node_ids += 1
            return
        self.nodes_by_id[node_id] = {
            "id": node_id,
            "label": label,
            "name": clean_text(name),
            "source_id": clean_text(source_id),
            "properties_json": json.dumps(properties or {}, ensure_ascii=False, sort_keys=True),
        }

    def _add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        raw_type: str = "",
        properties: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        edge_id = edge_identifier(source_id, target_id, edge_type, raw_type)
        if edge_id in self.edges_by_id:
            self.duplicate_edge_ids += 1
            return None
        edge = {
            "id": edge_id,
            "type": edge_type,
            "source_id": source_id,
            "target_id": target_id,
            "raw_type": clean_text(raw_type),
            "properties_json": json.dumps(properties or {}, ensure_ascii=False, sort_keys=True),
        }
        self.edges_by_id[edge_id] = edge
        self.edge_type_counts[edge_type] = self.edge_type_counts.get(edge_type, 0) + 1
        return edge

    def _summary(self) -> Dict[str, Any]:
        label_counts: Dict[str, int] = {}
        for node in self.nodes_by_id.values():
            label = node["label"]
            label_counts[label] = label_counts.get(label, 0) + 1

        return {
            "node_count": len(self.nodes_by_id),
            "edge_count": len(self.edges_by_id),
            "document_nodes": len(self.documents),
            "chunk_nodes": len(self.chunks),
            "node_labels": label_counts,
            "edge_types": dict(sorted(self.edge_type_counts.items())),
            "raw_relationship_labels": dict(sorted(self.raw_relationship_counts.items())),
            "orphan_document_relationship_edges": self.orphan_document_relationship_edges,
            "self_loop_document_relationship_edges": self.self_loop_document_relationship_edges,
            "orphan_chunk_rows": self.orphan_chunk_rows,
            "duplicate_node_ids": self.duplicate_node_ids,
            "duplicate_edge_ids": self.duplicate_edge_ids,
        }


def build_graph_tables(
    metadata_rows: Iterable[Dict[str, Any]],
    relationship_rows: Iterable[Dict[str, Any]],
    chunk_rows: Optional[Iterable[Dict[str, Any]]] = None,
) -> GraphTables:
    return GraphBuilder().build(
        metadata_rows=records(metadata_rows),
        relationship_rows=records(relationship_rows),
        chunk_rows=records(chunk_rows) if chunk_rows is not None else None,
    )


def export_graph_artifacts(graph: GraphTables, output_dir: Path | str) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    write_csv(output_path / "nodes.csv", graph.nodes, NODE_FIELDS)
    write_csv(output_path / "edges.csv", graph.edges, EDGE_FIELDS)
    write_csv(output_path / "documents.csv", graph.documents, DOCUMENT_FIELDS)
    write_csv(output_path / "document_relationship_edges.csv", graph.document_relationship_edges, EDGE_FIELDS)

    if graph.chunks:
        write_csv(output_path / "chunks.csv", graph.chunks, CHUNK_FIELDS)
    if graph.chunk_edges:
        write_csv(output_path / "chunk_edges.csv", graph.chunk_edges, EDGE_FIELDS)

    with (output_path / "graph_summary.json").open("w", encoding="utf-8") as f:
        json.dump(graph.summary, f, ensure_ascii=False, indent=2, sort_keys=True)

    (output_path / "neo4j_import.cypher").write_text(neo4j_import_cypher(), encoding="utf-8")


def write_csv(path: Path, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def records(rows: Any) -> List[Dict[str, Any]]:
    if rows is None:
        return []
    if isinstance(rows, list):
        return rows
    if hasattr(rows, "to_dict"):
        try:
            return rows.to_dict(orient="records")
        except TypeError:
            pass
    if hasattr(rows, "to_pylist"):
        return rows.to_pylist()
    return list(rows)


def document_node_id(doc_id: Any) -> str:
    return f"doc:{clean_text(doc_id)}"


def chunk_node_id(chunk_id: Any) -> str:
    value = clean_text(chunk_id)
    if value.startswith("chunk:"):
        return value
    return f"chunk:{value}"


def edge_identifier(source_id: str, target_id: str, edge_type: str, raw_type: str = "") -> str:
    raw = f":{slugify(raw_type)}" if raw_type else ""
    return f"{edge_type}:{source_id}->{target_id}{raw}"


def neo4j_import_cypher() -> str:
    return """// Run from Neo4j Browser or cypher-shell after placing CSV files in Neo4j import directory.
CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT legal_type_id IF NOT EXISTS FOR (n:LegalType) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT authority_id IF NOT EXISTS FOR (n:Authority) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT sector_id IF NOT EXISTS FOR (n:Sector) REQUIRE n.id IS UNIQUE;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
CALL {
  WITH row
  WITH row WHERE row.label = 'Document'
  MERGE (n:Document {id: row.id})
  SET n.name = row.name, n.source_id = row.source_id, n.properties_json = row.properties_json
} IN TRANSACTIONS OF 10000 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
CALL {
  WITH row
  WITH row WHERE row.label = 'Chunk'
  MERGE (n:Chunk {id: row.id})
  SET n.name = row.name, n.source_id = row.source_id, n.properties_json = row.properties_json
} IN TRANSACTIONS OF 10000 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
CALL {
  WITH row
  WITH row WHERE row.label = 'LegalType'
  MERGE (n:LegalType {id: row.id})
  SET n.name = row.name, n.properties_json = row.properties_json
} IN TRANSACTIONS OF 10000 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
CALL {
  WITH row
  WITH row WHERE row.label = 'Authority'
  MERGE (n:Authority {id: row.id})
  SET n.name = row.name, n.properties_json = row.properties_json
} IN TRANSACTIONS OF 10000 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
CALL {
  WITH row
  WITH row WHERE row.label = 'Sector'
  MERGE (n:Sector {id: row.id})
  SET n.name = row.name, n.properties_json = row.properties_json
} IN TRANSACTIONS OF 10000 ROWS;

LOAD CSV WITH HEADERS FROM 'file:///edges.csv' AS row
MATCH (source {id: row.source_id})
MATCH (target {id: row.target_id})
CALL apoc.create.relationship(source, row.type, {
  id: row.id,
  raw_type: row.raw_type,
  properties_json: row.properties_json
}, target) YIELD rel
RETURN count(rel);
"""


def read_parquet_records(path: Path | str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    import pandas as pd

    df = pd.read_parquet(path)
    if limit is not None:
        df = df.head(limit)
    return df.to_dict(orient="records")


def configure_stdout_for_utf8(stdout: Any = None) -> None:
    stream = stdout or sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    configure_stdout_for_utf8()
    parser = argparse.ArgumentParser(description="Build VietLegal Knowledge Graph artifacts.")
    parser.add_argument("--metadata", default="data/preprocessed/metadata.parquet")
    parser.add_argument("--relationships", default="data/preprocessed/relationships.parquet")
    parser.add_argument("--chunks", default=None)
    parser.add_argument("--output-dir", default="data/graph")
    parser.add_argument("--limit", type=int, default=None, help="Optional metadata row limit for smoke builds.")
    args = parser.parse_args(argv)

    metadata_rows = read_parquet_records(args.metadata, limit=args.limit)
    relationship_rows = read_parquet_records(args.relationships)
    if args.limit is not None:
        allowed_ids = {row.get("id") for row in metadata_rows}
        relationship_rows = [
            row for row in relationship_rows
            if row.get("doc_id") in allowed_ids or row.get("other_doc_id") in allowed_ids
        ]
    chunk_rows = read_parquet_records(args.chunks) if args.chunks else None

    graph = build_graph_tables(metadata_rows, relationship_rows, chunk_rows=chunk_rows)
    export_graph_artifacts(graph, args.output_dir)
    print(json.dumps(graph.summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
