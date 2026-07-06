from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


CANONICAL_RELATIONS = {"AMENDS", "CITES", "REPEALS", "GUIDELINES"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def audit_graph_artifacts(
    artifact_dir: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_path = Path(artifact_dir)
    documents = read_csv(artifact_path / "documents.csv")
    edges = read_csv(artifact_path / "document_relationship_edges.csv")
    chunks = read_csv(artifact_path / "chunks.csv")

    document_ids = {row.get("id", "") for row in documents}
    document_id_counts = Counter(row.get("id", "") for row in documents)
    chunk_id_counts = Counter(row.get("id", "") for row in chunks)

    missing_endpoint_edges = 0
    self_loop_edges = 0
    edges_missing_raw_label = 0
    unknown_relation_count = 0
    edge_type_counts: Counter[str] = Counter()

    for edge in edges:
        source = edge.get("source_id", "")
        target = edge.get("target_id", "")
        edge_type = edge.get("type", "")
        edge_type_counts[edge_type] += 1
        if source not in document_ids or target not in document_ids:
            missing_endpoint_edges += 1
        if source == target:
            self_loop_edges += 1
        if not edge.get("raw_label", "").strip():
            edges_missing_raw_label += 1
        if edge_type not in CANONICAL_RELATIONS:
            unknown_relation_count += 1

    summary = {
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "document_relationship_count": len(edges),
        "missing_endpoint_edges": missing_endpoint_edges,
        "self_loop_edges": self_loop_edges,
        "edges_missing_raw_label": edges_missing_raw_label,
        "unknown_canonical_relation_count": unknown_relation_count,
        "duplicate_document_ids": sum(1 for value in document_id_counts.values() if value > 1),
        "duplicate_article_or_chunk_ids": sum(1 for value in chunk_id_counts.values() if value > 1),
        "edge_type_counts": dict(sorted(edge_type_counts.items())),
    }

    if output_dir is not None:
        write_report(summary, Path(output_dir))

    return summary


def write_report(summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "kg_quality_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# KG Quality Report",
        "",
        f"- Documents: {summary['document_count']}",
        f"- Chunks: {summary['chunk_count']}",
        f"- Document relationships: {summary['document_relationship_count']}",
        f"- Missing endpoint edges: {summary['missing_endpoint_edges']}",
        f"- Self-loop edges: {summary['self_loop_edges']}",
        f"- Edges missing raw_label: {summary['edges_missing_raw_label']}",
        f"- Unknown canonical relations: {summary['unknown_canonical_relation_count']}",
        f"- Duplicate document IDs: {summary['duplicate_document_ids']}",
        f"- Duplicate article or chunk IDs: {summary['duplicate_article_or_chunk_ids']}",
        "",
        "### Edge Type Distribution",
    ]
    for edge_type, count in sorted(summary.get("edge_type_counts", {}).items()):
        lines.append(f"- {edge_type}: {count}")
    (output_dir / "kg_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit KG CSV artifacts for MVP invariants.")
    parser.add_argument("--artifact-dir", default="data/graph")
    parser.add_argument("--output-dir", default="output/kg_quality")
    args = parser.parse_args()
    summary = audit_graph_artifacts(args.artifact_dir, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
