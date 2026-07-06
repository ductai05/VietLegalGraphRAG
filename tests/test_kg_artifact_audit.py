import csv
import json
from pathlib import Path

from pipeline.graph.audit_graph_artifacts import audit_graph_artifacts


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Clean input path
# ---------------------------------------------------------------------------


def test_audit_graph_artifacts_reports_mvp_invariants(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [{"id": "doc:1", "doc_id": "1"}, {"id": "doc:2", "doc_id": "2"}],
    )
    write_csv(
        tmp_path / "document_relationship_edges.csv",
        [
            {
                "id": "e1",
                "type": "AMENDS",
                "source_id": "doc:2",
                "target_id": "doc:1",
                "raw_type": "Van ban sua doi",
                "raw_label": "Van ban sua doi",
                "properties_json": "{}",
            }
        ],
    )
    write_csv(
        tmp_path / "chunks.csv",
        [{"id": "chunk:1:000001", "chunk_id": "chunk:1:000001", "doc_id": "1"}],
    )

    summary = audit_graph_artifacts(tmp_path)

    assert summary["document_count"] == 2
    assert summary["document_relationship_count"] == 1
    assert summary["missing_endpoint_edges"] == 0
    assert summary["self_loop_edges"] == 0
    assert summary["edges_missing_raw_label"] == 0
    assert summary["unknown_canonical_relation_count"] == 0


# ---------------------------------------------------------------------------
# Missing endpoint edges  (source/target not in documents.csv)
# ---------------------------------------------------------------------------


def test_detects_missing_endpoint_edges(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [{"id": "doc:1", "doc_id": "1"}],
    )
    write_csv(
        tmp_path / "document_relationship_edges.csv",
        [
            {
                "id": "e1",
                "type": "CITES",
                "source_id": "doc:1",
                "target_id": "doc:999",
                "raw_type": "Van ban dan chieu",
                "raw_label": "Van ban dan chieu",
                "properties_json": "{}",
            }
        ],
    )

    summary = audit_graph_artifacts(tmp_path)
    assert summary["missing_endpoint_edges"] == 1


# ---------------------------------------------------------------------------
# Unknown canonical relation type
# ---------------------------------------------------------------------------


def test_detects_unknown_canonical_relation(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [{"id": "doc:1", "doc_id": "1"}, {"id": "doc:2", "doc_id": "2"}],
    )
    write_csv(
        tmp_path / "document_relationship_edges.csv",
        [
            {
                "id": "e1",
                "type": "SUSPENDS",
                "source_id": "doc:1",
                "target_id": "doc:2",
                "raw_type": "Dinh chi",
                "raw_label": "Dinh chi",
                "properties_json": "{}",
            }
        ],
    )

    summary = audit_graph_artifacts(tmp_path)
    assert summary["unknown_canonical_relation_count"] == 1


def test_detects_empty_type_as_unknown(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [{"id": "doc:1", "doc_id": "1"}, {"id": "doc:2", "doc_id": "2"}],
    )
    write_csv(
        tmp_path / "document_relationship_edges.csv",
        [
            {
                "id": "e1",
                "type": "",
                "source_id": "doc:1",
                "target_id": "doc:2",
                "raw_type": "",
                "raw_label": "",
                "properties_json": "{}",
            }
        ],
    )

    summary = audit_graph_artifacts(tmp_path)
    assert summary["unknown_canonical_relation_count"] == 1


# ---------------------------------------------------------------------------
# Duplicate document IDs
# ---------------------------------------------------------------------------


def test_detects_duplicate_document_ids(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [
            {"id": "doc:1", "doc_id": "1"},
            {"id": "doc:1", "doc_id": "1"},  # duplicate row
            {"id": "doc:2", "doc_id": "2"},
        ],
    )

    summary = audit_graph_artifacts(tmp_path)
    assert summary["duplicate_document_ids"] == 1


# ---------------------------------------------------------------------------
# Duplicate chunk IDs
# ---------------------------------------------------------------------------


def test_detects_duplicate_chunk_ids(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [{"id": "doc:1", "doc_id": "1"}],
    )
    write_csv(
        tmp_path / "chunks.csv",
        [
            {"id": "chunk:1:000001", "chunk_id": "chunk:1:000001", "doc_id": "1"},
            {"id": "chunk:1:000001", "chunk_id": "chunk:1:000001", "doc_id": "1"},
        ],
    )

    summary = audit_graph_artifacts(tmp_path)
    assert summary["duplicate_article_or_chunk_ids"] == 1


# ---------------------------------------------------------------------------
# Whitespace-only raw_label (not just empty string)
# ---------------------------------------------------------------------------


def test_detects_whitespace_only_raw_label(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [{"id": "doc:1", "doc_id": "1"}, {"id": "doc:2", "doc_id": "2"}],
    )
    write_csv(
        tmp_path / "document_relationship_edges.csv",
        [
            {
                "id": "e1",
                "type": "CITES",
                "source_id": "doc:1",
                "target_id": "doc:2",
                "raw_type": "   ",
                "raw_label": "   ",  # whitespace-only
                "properties_json": "{}",
            }
        ],
    )

    summary = audit_graph_artifacts(tmp_path)
    assert summary["edges_missing_raw_label"] == 1


# ---------------------------------------------------------------------------
# Partial artifact directory  (missing files should not crash)
# ---------------------------------------------------------------------------


def test_missing_files_returns_zero_counts(tmp_path: Path) -> None:
    # No files written at all — only an empty directory
    summary = audit_graph_artifacts(tmp_path)

    assert summary["document_count"] == 0
    assert summary["chunk_count"] == 0
    assert summary["document_relationship_count"] == 0
    assert summary["missing_endpoint_edges"] == 0
    assert summary["self_loop_edges"] == 0
    assert summary["edges_missing_raw_label"] == 0
    assert summary["unknown_canonical_relation_count"] == 0


# ---------------------------------------------------------------------------
# Edge type count distribution
# ---------------------------------------------------------------------------


def test_edge_type_counts_distribution(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [
            {"id": "doc:1", "doc_id": "1"},
            {"id": "doc:2", "doc_id": "2"},
            {"id": "doc:3", "doc_id": "3"},
            {"id": "doc:4", "doc_id": "4"},
        ],
    )
    write_csv(
        tmp_path / "document_relationship_edges.csv",
        [
            {
                "id": "e1",
                "type": "AMENDS",
                "source_id": "doc:2",
                "target_id": "doc:1",
                "raw_type": "Van ban sua doi",
                "raw_label": "Van ban sua doi",
                "properties_json": "{}",
            },
            {
                "id": "e2",
                "type": "CITES",
                "source_id": "doc:1",
                "target_id": "doc:3",
                "raw_type": "Van ban dan chieu",
                "raw_label": "Van ban dan chieu",
                "properties_json": "{}",
            },
            {
                "id": "e3",
                "type": "CITES",
                "source_id": "doc:3",
                "target_id": "doc:4",
                "raw_type": "Van ban can cu",
                "raw_label": "Van ban can cu",
                "properties_json": "{}",
            },
            {
                "id": "e4",
                "type": "REPEALS",
                "source_id": "doc:4",
                "target_id": "doc:2",
                "raw_type": "Van ban het hieu luc",
                "raw_label": "Van ban het hieu luc",
                "properties_json": "{}",
            },
        ],
    )

    summary = audit_graph_artifacts(tmp_path)
    assert summary["edge_type_counts"] == {"AMENDS": 1, "CITES": 2, "REPEALS": 1}


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------


def test_audit_graph_artifacts_writes_report(tmp_path: Path) -> None:
    write_csv(tmp_path / "documents.csv", [{"id": "doc:1", "doc_id": "1"}])
    write_csv(
        tmp_path / "document_relationship_edges.csv",
        [
            {
                "id": "e1",
                "type": "CITES",
                "source_id": "doc:1",
                "target_id": "doc:1",
                "raw_type": "Van ban dan chieu",
                "raw_label": "",
                "properties_json": "{}",
            }
        ],
    )

    summary = audit_graph_artifacts(tmp_path, output_dir=tmp_path / "report")

    report_json = json.loads(
        (tmp_path / "report" / "kg_quality_summary.json").read_text(encoding="utf-8")
    )
    report_md = (tmp_path / "report" / "kg_quality_report.md").read_text(encoding="utf-8")
    assert report_json["self_loop_edges"] == 1
    assert summary["edges_missing_raw_label"] == 1
    assert "KG Quality Report" in report_md


def test_report_includes_duplicates_and_edge_types(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "documents.csv",
        [
            {"id": "doc:1", "doc_id": "1"},
            {"id": "doc:1", "doc_id": "1"},  # duplicate
            {"id": "doc:2", "doc_id": "2"},
        ],
    )
    write_csv(
        tmp_path / "document_relationship_edges.csv",
        [
            {
                "id": "e1",
                "type": "AMENDS",
                "source_id": "doc:1",
                "target_id": "doc:2",
                "raw_type": "Van ban sua doi",
                "raw_label": "Van ban sua doi",
                "properties_json": "{}",
            },
            {
                "id": "e2",
                "type": "CITES",
                "source_id": "doc:2",
                "target_id": "doc:1",
                "raw_type": "Van ban dan chieu",
                "raw_label": "Van ban dan chieu",
                "properties_json": "{}",
            },
        ],
    )

    audit_graph_artifacts(tmp_path, output_dir=tmp_path / "report")
    report_md = (tmp_path / "report" / "kg_quality_report.md").read_text(encoding="utf-8")

    assert "Duplicate document IDs: 1" in report_md
    assert "AMENDS: 1" in report_md
    assert "CITES: 1" in report_md
