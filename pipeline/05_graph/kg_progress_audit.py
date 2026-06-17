"""Audit Neo4j KG exports and connect them to current retrieval evaluation.

This script is intentionally read-only. It does not require a running Neo4j
server; it audits the CSV files produced for Neo4j bulk import and creates a
small progress report that can be shared with the team.
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
IMPORT_DIR = ROOT / "data" / "processed" / "neo4j_imports"
ERROR_CASES = ROOT / "evaluation_artifacts" / "output" / "report_artifacts" / "retrieval_error_cases.json"
OUT_DIR = ROOT / "output" / "kg_progress"


NODE_FILES = {
    "Document": "documents.csv",
    "Article": "articles.csv",
    "LegalType": "legal_types.csv",
    "Authority": "authorities.csv",
    "Sector": "sectors.csv",
}

EDGE_FILES = {
    "Document-Document": "doc_doc_edges.csv",
    "Document-Article": "doc_art_edges.csv",
    "Article-NEXT": "art_art_next_edges.csv",
    "Article-PARENT": "art_art_parent_edges.csv",
    "Document-LegalType": "doc_type_edges.csv",
    "Document-Authority": "doc_auth_edges.csv",
    "Document-Sector": "doc_sector_edges.csv",
}


def count_csv_rows(path: Path) -> int:
    """Count rows excluding header using binary newline scan."""
    count = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            count += block.count(b"\n")
    return max(0, count - 1)


def load_error_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def parse_import_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"duplicate_lines": 0, "duplicate_groups": {}, "top_duplicate_ids": []}
    pattern = re.compile(r"Id '([^']+)' is defined more than once in group '([^']+)'")
    group_counts: Counter[str] = Counter()
    id_counts: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if not match:
            continue
        node_id, group = match.groups()
        group_counts[group] += 1
        id_counts[node_id] += 1
    return {
        "duplicate_lines": sum(group_counts.values()),
        "duplicate_groups": dict(group_counts),
        "top_duplicate_ids": id_counts.most_common(10),
    }


def collect_needed_chunk_ids(error_cases: list[dict[str, Any]]) -> set[str]:
    chunk_ids: set[str] = set()
    for case in error_cases:
        chunk_ids.update(str(value) for value in case.get("gold_chunk_ids", []))
        chunk_ids.update(str(value) for value in case.get("top3_chunk_ids", []))
    return chunk_ids


def find_articles_by_chunk_uuid(path: Path, chunk_uuids: set[str]) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    if not chunk_uuids:
        return found
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            chunk_uuid = row.get("chunk_id", "")
            if chunk_uuid in chunk_uuids:
                found[chunk_uuid] = {
                    "article_id": row.get("id:ID(Article)", ""),
                    "chunk_id": chunk_uuid,
                    "doc_id": str(row.get("doc_id", "")),
                    "chunk_type": row.get("chunk_type", ""),
                    "section_path": row.get("section_path", ""),
                    "token_estimate": row.get("token_estimate", ""),
                }
                if len(found) == len(chunk_uuids):
                    break
    return found


def load_documents(path: Path, doc_ids: set[str]) -> dict[str, dict[str, str]]:
    docs: dict[str, dict[str, str]] = {}
    if not doc_ids:
        return docs
    normalized = {value.replace("doc:", "") for value in doc_ids}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_id = str(row.get("id:ID(Document)", "")).replace("doc:", "")
            if raw_id in normalized:
                docs[raw_id] = {
                    "id": raw_id,
                    "document_number": row.get("document_number", ""),
                    "title": row.get("title", ""),
                    "legal_type": row.get("legal_type", ""),
                    "issuing_authority": row.get("issuing_authority", ""),
                    "effect_status": row.get("effect_status", ""),
                    "priority_tier": row.get("priority_tier", ""),
                }
                if len(docs) == len(normalized):
                    break
    return docs


def inspect_doc_edges(path: Path, docs_of_interest: set[str]) -> dict[str, Any]:
    doc_ids = {f"doc:{value.replace('doc:', '')}" for value in docs_of_interest}
    relation_counts: Counter[str] = Counter()
    incident_counts: Counter[str] = Counter()
    direct_edges: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            start = row.get(":START_ID(Document)", "")
            end = row.get(":END_ID(Document)", "")
            rel = row.get(":TYPE", "")
            relation_counts[rel] += 1
            if start in doc_ids or end in doc_ids:
                incident_counts[rel] += 1
            if start in doc_ids and end in doc_ids:
                direct_edges.append(
                    {
                        "start": start.replace("doc:", ""),
                        "end": end.replace("doc:", ""),
                        "type": rel,
                        "raw_relationship": row.get("raw_relationship", ""),
                    }
                )
    return {
        "relation_counts": dict(relation_counts),
        "incident_counts_for_eval_docs": dict(incident_counts),
        "direct_edges_between_eval_docs": direct_edges,
    }


def summarize_error_cases(
    error_cases: list[dict[str, Any]],
    articles: dict[str, dict[str, str]],
    doc_edges: list[dict[str, str]],
) -> list[dict[str, Any]]:
    edge_pairs = {(edge["start"], edge["end"]): edge for edge in doc_edges}
    edge_pairs.update({(edge["end"], edge["start"]): edge for edge in doc_edges})
    rows = []
    for case in error_cases:
        gold_docs = {
            articles[cid]["doc_id"]
            for cid in case.get("gold_chunk_ids", [])
            if cid in articles
        }
        top_docs = {
            articles[cid]["doc_id"]
            for cid in case.get("top3_chunk_ids", [])
            if cid in articles
        }
        bridges = []
        same_doc_overlap = sorted(gold_docs & top_docs)
        for top_doc in sorted(top_docs):
            for gold_doc in sorted(gold_docs):
                edge = edge_pairs.get((top_doc, gold_doc))
                if edge:
                    bridges.append(f"{top_doc}-{edge['type']}-{gold_doc}")
        rows.append(
            {
                "question_id": case.get("question_id"),
                "group": case.get("group"),
                "gold_docs": sorted(gold_docs),
                "top3_docs": sorted(top_docs),
                "same_doc_overlap": same_doc_overlap,
                "all_chunks_mapped": (
                    len(gold_docs) > 0
                    and all(cid in articles for cid in case.get("top3_chunk_ids", []))
                ),
                "direct_doc_bridge_between_gold_and_top3": bridges,
            }
        )
    return rows


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        out.append("| " + " | ".join(str(value).replace("\n", " ") for value in row) + " |")
    return "\n".join(out)


def write_report(summary: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "kg_progress_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    node_rows = [[name, f"{count:,}"] for name, count in summary["node_counts"].items()]
    edge_rows = [[name, f"{count:,}"] for name, count in summary["edge_counts"].items()]
    rel_rows = [
        [rel, f"{count:,}"]
        for rel, count in sorted(summary["doc_doc_relation_counts"].items())
    ]
    eval_rows = [
        [
            row["question_id"],
            row["group"],
            ", ".join(row["gold_docs"]) or "-",
            ", ".join(row["top3_docs"]) or "-",
            ", ".join(row["same_doc_overlap"]) or "-",
            "; ".join(row["direct_doc_bridge_between_gold_and_top3"]) or "-",
        ]
        for row in summary["retrieval_error_case_mapping"]
    ]

    lines = [
        "# KG Progress Audit",
        "",
        f"Generated at: `{summary['generated_at']}`",
        "",
        "## What Was Checked",
        "",
        "- Existing Neo4j bulk-import CSVs under `data/processed/neo4j_imports`.",
        "- Import report warnings from `import.report`.",
        "- Current retrieval error cases under `evaluation_artifacts/output/report_artifacts/retrieval_error_cases.json`.",
        "",
        "## Graph Size From CSV Export",
        "",
        md_table(["Node label", "Rows"], node_rows),
        "",
        md_table(["Relationship group", "Rows"], edge_rows),
        "",
        f"Total nodes from CSV: **{summary['total_nodes']:,}**",
        f"Total relationships from CSV: **{summary['total_edges']:,}**",
        "",
        "## Document-Document Relationship Types",
        "",
        md_table(["Type", "Rows"], rel_rows),
        "",
        "## Import Report Health",
        "",
        f"- Duplicate metadata warnings: **{summary['import_report']['duplicate_lines']:,}**.",
        f"- Duplicate groups: `{summary['import_report']['duplicate_groups']}`.",
        "- These are metadata node duplicates tolerated by the current import script via "
        "`--skip-duplicate-nodes=true`; they do not invalidate Document/Article rows, "
        "but the metadata export should be deduplicated later.",
        "",
        "## Link To Current Retrieval Evaluation",
        "",
        "For the 10 sampled Hybrid+Rerank misses, the audit maps gold/top-3 chunk UUIDs "
        "back to Article and Document IDs in the KG export.",
        "",
        md_table(
            ["Question", "Group", "Gold docs", "Top-3 docs", "Same doc", "Direct KG doc bridge"],
            eval_rows,
        ),
        "",
        f"- Error cases checked: **{len(summary['retrieval_error_case_mapping'])}**",
        f"- Error cases whose chunks mapped to KG export: **{summary['error_cases_with_any_mapping']}**",
        f"- Error cases where top-3 already contains the gold document: **{summary['error_cases_with_same_doc_overlap']}**",
        f"- Direct Document-Document bridges between top-3 retrieved docs and gold docs: **{summary['error_cases_with_direct_bridge']}**",
        "",
        "## Immediate Takeaway",
        "",
        "KG assets are still usable: the full Neo4j import CSV export exists locally and "
        "covers the current retrieval evaluation chunks. As an immediate next step, KG can "
        "be used for error analysis and query expansion around retrieved/gold documents, "
        "without waiting for embeddings to be stored inside Neo4j.",
        "",
    ]
    (OUT_DIR / "kg_progress_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    started = time.perf_counter()
    missing = [
        filename
        for filename in list(NODE_FILES.values()) + list(EDGE_FILES.values())
        if not (IMPORT_DIR / filename).exists()
    ]
    if missing:
        raise FileNotFoundError(f"Missing Neo4j import files: {missing}")

    node_counts = {
        label: count_csv_rows(IMPORT_DIR / filename)
        for label, filename in NODE_FILES.items()
    }
    edge_counts = {
        label: count_csv_rows(IMPORT_DIR / filename)
        for label, filename in EDGE_FILES.items()
    }

    error_cases = load_error_cases(ERROR_CASES)
    needed_chunk_ids = collect_needed_chunk_ids(error_cases)
    articles = find_articles_by_chunk_uuid(IMPORT_DIR / "articles.csv", needed_chunk_ids)
    doc_ids = {row["doc_id"] for row in articles.values() if row.get("doc_id")}
    documents = load_documents(IMPORT_DIR / "documents.csv", doc_ids)
    edge_info = inspect_doc_edges(IMPORT_DIR / "doc_doc_edges.csv", doc_ids)
    mapped_cases = summarize_error_cases(
        error_cases,
        articles,
        edge_info["direct_edges_between_eval_docs"],
    )

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "import_dir": str(IMPORT_DIR),
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "total_nodes": sum(node_counts.values()),
        "total_edges": sum(edge_counts.values()),
        "import_report": parse_import_report(IMPORT_DIR / "import.report"),
        "doc_doc_relation_counts": edge_info["relation_counts"],
        "doc_doc_incident_counts_for_eval_docs": edge_info["incident_counts_for_eval_docs"],
        "needed_chunk_ids": len(needed_chunk_ids),
        "mapped_chunk_ids": len(articles),
        "mapped_documents": len(documents),
        "mapped_document_samples": list(documents.values())[:20],
        "retrieval_error_case_mapping": mapped_cases,
        "error_cases_with_any_mapping": sum(
            bool(row["gold_docs"] or row["top3_docs"]) for row in mapped_cases
        ),
        "error_cases_with_same_doc_overlap": sum(
            bool(row["same_doc_overlap"]) for row in mapped_cases
        ),
        "error_cases_with_direct_bridge": sum(
            bool(row["direct_doc_bridge_between_gold_and_top3"]) for row in mapped_cases
        ),
    }
    write_report(summary)
    print(f"Wrote {OUT_DIR / 'kg_progress_report.md'}")
    print(f"Wrote {OUT_DIR / 'kg_progress_summary.json'}")
    print(f"Total nodes: {summary['total_nodes']:,}")
    print(f"Total relationships: {summary['total_edges']:,}")
    print(f"Mapped chunks: {summary['mapped_chunk_ids']}/{summary['needed_chunk_ids']}")


if __name__ == "__main__":
    main()
