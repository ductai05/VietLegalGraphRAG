import csv
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "05_graph"))


def test_normalizes_relationship_labels():
    from schema import normalize_relationship_label

    expected = {
        "Văn bản căn cứ": "CITES_AS_BASIS",
        "Văn bản dẫn chiếu": "CITES",
        "Văn bản HD, QĐ chi tiết": "GUIDES_DETAIL",
        "Văn bản được HD, QĐ chi tiết": "IS_GUIDED_DETAILED_BY",
        "Văn bản sửa đổi": "AMENDS",
        "Văn bản được sửa đổi": "IS_AMENDED_BY",
        "Văn bản bổ sung": "SUPPLEMENTS",
        "Văn bản được bổ sung": "IS_SUPPLEMENTED_BY",
        "Văn bản quy định hết hiệu lực": "REPLACES_OR_EXPIRES",
        "Văn bản quy định hết hiệu lực 1 phần": "REPLACES_OR_EXPIRES",
        "Văn bản hết hiệu lực": "IS_REPLACED_OR_EXPIRED_BY",
        "Văn bản bị hết hiệu lực 1 phần": "IS_REPLACED_OR_EXPIRED_BY",
        "Văn bản đình chỉ 1 phần": "SUSPENDS",
        "Văn bản bị đình chỉ 1 phần": "IS_SUSPENDED_BY",
        "Văn bản liên quan khác": "RELATED_TO",
    }

    for raw_label, edge_type in expected.items():
        assert normalize_relationship_label(raw_label).edge_type == edge_type


def test_builds_document_graph_tables():
    from build_graph import build_graph_tables

    metadata_rows = [
        {
            "id": 1,
            "document_number": "01/2026/QH",
            "title": "Luật kiểm thử",
            "legal_type": "Luật",
            "legal_sectors": "Thuế, Phí",
            "issuing_authority": "Quốc hội",
            "issuance_date": "2026-01-01",
            "effect_date": "2026-02-01",
            "effectless_date": None,
            "effect_status": "Còn hiệu lực",
            "signers": "Chủ tịch Quốc hội",
            "source": "unit",
        },
        {
            "id": 2,
            "document_number": "02/2026/NĐ-CP",
            "title": "Nghị định kiểm thử",
            "legal_type": "Nghị định",
            "legal_sectors": "Thuế",
            "issuing_authority": "Chính phủ",
            "issuance_date": "2026-01-15",
            "effect_date": "2026-02-15",
            "effectless_date": None,
            "effect_status": "Còn hiệu lực",
            "signers": "Thủ tướng",
            "source": "unit",
        },
    ]
    relationship_rows = [
        {"doc_id": 2, "other_doc_id": 1, "relationship": "Văn bản căn cứ"},
        {"doc_id": 99, "other_doc_id": 1, "relationship": "Văn bản căn cứ"},
    ]

    graph = build_graph_tables(metadata_rows, relationship_rows)

    node_ids = {row["id"] for row in graph.nodes}
    assert {"doc:1", "doc:2", "legal_type:luat", "authority:quoc-hoi", "sector:thue"} <= node_ids

    doc_1 = next(row for row in graph.documents if row["id"] == "doc:1")
    assert doc_1["priority_tier"] == "tier_1"
    assert doc_1["sector_list"] == "Thuế|Phí"

    edge_types = {(row["source_id"], row["target_id"], row["type"]) for row in graph.edges}
    assert ("doc:2", "doc:1", "CITES_AS_BASIS") in edge_types
    assert ("doc:1", "legal_type:luat", "HAS_LEGAL_TYPE") in edge_types
    assert ("doc:1", "authority:quoc-hoi", "ISSUED_BY") in edge_types
    assert ("doc:1", "sector:thue", "IN_SECTOR") in edge_types
    assert graph.summary["orphan_document_relationship_edges"] == 1
    assert graph.summary["duplicate_node_ids"] == 0


def test_attaches_chunks_to_documents():
    from build_graph import build_graph_tables

    graph = build_graph_tables(
        metadata_rows=[
            {
                "id": 1,
                "document_number": "01/2026/QH",
                "title": "Luật kiểm thử",
                "legal_type": "Luật",
                "legal_sectors": "Thuế",
                "issuing_authority": "Quốc hội",
                "issuance_date": "2026-01-01",
                "effect_status": "Còn hiệu lực",
                "source": "unit",
            }
        ],
        relationship_rows=[],
        chunk_rows=[
            {
                "chunk_id": "chunk:1:000001",
                "doc_id": 1,
                "chunk_type": "article",
                "section_path": ["Điều 1"],
                "procedure_name": None,
                "embed": True,
                "keyword_index": True,
                "parent_id": "parent-a",
                "prev_chunk_id": None,
                "next_chunk_id": "chunk:1:000002",
                "token_estimate": 30,
                "quality_flags": [],
            },
            {
                "chunk_id": "chunk:1:000002",
                "doc_id": 1,
                "chunk_type": "article",
                "section_path": ["Điều 2"],
                "procedure_name": None,
                "embed": True,
                "keyword_index": True,
                "parent_id": "chunk:1:000001",
                "prev_chunk_id": "chunk:1:000001",
                "next_chunk_id": None,
                "token_estimate": 35,
                "quality_flags": [],
            },
        ],
    )

    edge_types = {(row["source_id"], row["target_id"], row["type"]) for row in graph.edges}
    assert ("doc:1", "chunk:chunk:1:000001", "HAS_CHUNK") in edge_types
    assert ("chunk:chunk:1:000001", "chunk:chunk:1:000002", "NEXT_CHUNK") in edge_types
    assert ("chunk:chunk:1:000001", "chunk:chunk:1:000002", "PARENT_OF") in edge_types
    assert graph.summary["chunk_nodes"] == 2


def test_exports_graph_artifacts(tmp_path):
    from build_graph import build_graph_tables, export_graph_artifacts

    graph = build_graph_tables(
        metadata_rows=[
            {
                "id": 1,
                "document_number": "01/2026/QH",
                "title": "Luật kiểm thử",
                "legal_type": "Luật",
                "legal_sectors": "Thuế",
                "issuing_authority": "Quốc hội",
                "issuance_date": "2026-01-01",
                "effect_status": "Còn hiệu lực",
                "source": "unit",
            }
        ],
        relationship_rows=[],
    )

    export_graph_artifacts(graph, tmp_path)

    expected_files = {
        "nodes.csv",
        "edges.csv",
        "documents.csv",
        "document_relationship_edges.csv",
        "graph_summary.json",
        "neo4j_import.cypher",
    }
    assert expected_files <= {path.name for path in tmp_path.iterdir()}

    with (tmp_path / "nodes.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert any(row["id"] == "doc:1" and row["label"] == "Document" for row in rows)

    with (tmp_path / "graph_summary.json").open(encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["document_nodes"] == 1
    assert summary["duplicate_node_ids"] == 0


def test_configures_stdout_for_utf8_when_supported():
    from build_graph import configure_stdout_for_utf8

    class FakeStdout:
        encoding = "cp1252"

        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    stdout = FakeStdout()
    configure_stdout_for_utf8(stdout)
    assert stdout.calls == [{"encoding": "utf-8"}]
