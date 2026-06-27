import csv
import json
from pathlib import Path

from audit_graph_artifacts import audit_graph_artifacts


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


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
