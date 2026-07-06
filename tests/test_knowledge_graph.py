import csv
import json
import tempfile
from pathlib import Path

def test_normalizes_relationship_labels_to_four_canonical_types():
    from pipeline.graph.schema import normalize_relationship_label

    expected = {
        "V\u0103n b\u1ea3n c\u0103n c\u1ee9": ("CITES", False),
        "V\u0103n b\u1ea3n d\u1eabn chi\u1ebfu": ("CITES", False),
        "V\u0103n b\u1ea3n HD, Q\u0110 chi ti\u1ebft": ("GUIDELINES", False),
        "V\u0103n b\u1ea3n \u0111\u01b0\u1ee3c HD, Q\u0110 chi ti\u1ebft": ("GUIDELINES", True),
        "V\u0103n b\u1ea3n s\u1eeda \u0111\u1ed5i": ("AMENDS", False),
        "V\u0103n b\u1ea3n \u0111\u01b0\u1ee3c s\u1eeda \u0111\u1ed5i": ("AMENDS", True),
        "V\u0103n b\u1ea3n b\u1ed5 sung": ("AMENDS", False),
        "V\u0103n b\u1ea3n \u0111\u01b0\u1ee3c b\u1ed5 sung": ("AMENDS", True),
        "V\u0103n b\u1ea3n quy \u0111\u1ecbnh h\u1ebft hi\u1ec7u l\u1ef1c": ("REPEALS", False),
        "V\u0103n b\u1ea3n quy \u0111\u1ecbnh h\u1ebft hi\u1ec7u l\u1ef1c 1 ph\u1ea7n": ("REPEALS", False),
        "V\u0103n b\u1ea3n h\u1ebft hi\u1ec7u l\u1ef1c": ("REPEALS", True),
        "V\u0103n b\u1ea3n b\u1ecb h\u1ebft hi\u1ec7u l\u1ef1c 1 ph\u1ea7n": ("REPEALS", True),
        "V\u0103n b\u1ea3n \u0111\u00ecnh ch\u1ec9 1 ph\u1ea7n": ("REPEALS", False),
        "V\u0103n b\u1ea3n b\u1ecb \u0111\u00ecnh ch\u1ec9 1 ph\u1ea7n": ("REPEALS", True),
        "V\u0103n b\u1ea3n li\u00ean quan kh\u00e1c": ("CITES", False),
    }

    for raw_label, (edge_type, reverse_direction) in expected.items():
        normalized = normalize_relationship_label(raw_label)
        assert normalized.edge_type == edge_type
        assert normalized.reverse_direction is reverse_direction


def test_skips_self_loops_and_reverses_passive_relationships():
    from pipeline.graph.build_graph import build_graph_tables

    passive_amend = "V\u0103n b\u1ea3n \u0111\u01b0\u1ee3c s\u1eeda \u0111\u1ed5i"
    citation = "V\u0103n b\u1ea3n d\u1eabn chi\u1ebfu"
    graph = build_graph_tables(
        metadata_rows=[
            {"id": 1, "title": "Document A"},
            {"id": 2, "title": "Document B"},
        ],
        relationship_rows=[
            {"doc_id": 1, "other_doc_id": 1, "relationship": citation},
            {"doc_id": 1, "other_doc_id": 2, "relationship": passive_amend},
        ],
    )

    doc_edges = {
        (row["source_id"], row["target_id"], row["type"], row["raw_type"])
        for row in graph.document_relationship_edges
    }
    assert ("doc:1", "doc:1", "CITES", citation) not in doc_edges
    assert ("doc:2", "doc:1", "AMENDS", passive_amend) in doc_edges
    assert graph.summary["self_loop_document_relationship_edges"] == 1


def test_document_relationship_edges_preserve_raw_label_for_export_and_neo4j():
    from pipeline.graph.build_graph import build_graph_tables, export_graph_artifacts

    raw_label = "V\u0103n b\u1ea3n \u0111\u01b0\u1ee3c s\u1eeda \u0111\u1ed5i"
    graph = build_graph_tables(
        metadata_rows=[
            {"id": 1, "title": "Document A"},
            {"id": 2, "title": "Document B"},
        ],
        relationship_rows=[
            {"doc_id": 1, "other_doc_id": 2, "relationship": raw_label},
        ],
    )
    edge = graph.document_relationship_edges[0]
    properties = json.loads(edge["properties_json"])

    assert edge["raw_label"] == raw_label
    assert properties["raw_label"] == raw_label
    assert properties["raw_relationship"] == raw_label

    with tempfile.TemporaryDirectory() as tmp_dir:
        export_graph_artifacts(graph, Path(tmp_dir))
        with (Path(tmp_dir) / "document_relationship_edges.csv").open(
            encoding="utf-8",
            newline="",
        ) as handle:
            row = next(csv.DictReader(handle))
        cypher = (Path(tmp_dir) / "neo4j_import.cypher").read_text(encoding="utf-8")

    assert row["raw_label"] == raw_label
    assert "raw_label: row.raw_label" in cypher


def test_builds_document_graph_tables():
    from pipeline.graph.build_graph import build_graph_tables

    metadata_rows = [
        {
            "id": 1,
            "document_number": "01/2026/QH",
            "title": "Luat kiem thu",
            "legal_type": "Luat",
            "legal_sectors": "Thue, Phi",
            "issuing_authority": "Quoc hoi",
            "issuance_date": "2026-01-01",
            "effect_date": "2026-02-01",
            "effectless_date": None,
            "effect_status": "Con hieu luc",
            "signers": "Chu tich Quoc hoi",
            "source": "unit",
        },
        {
            "id": 2,
            "document_number": "02/2026/ND-CP",
            "title": "Nghi dinh kiem thu",
            "legal_type": "Nghi dinh",
            "legal_sectors": "Thue",
            "issuing_authority": "Chinh phu",
            "issuance_date": "2026-01-15",
            "effect_date": "2026-02-15",
            "effectless_date": None,
            "effect_status": "Con hieu luc",
            "signers": "Thu tuong",
            "source": "unit",
        },
    ]
    relationship_rows = [
        {"doc_id": 2, "other_doc_id": 1, "relationship": "V\u0103n b\u1ea3n c\u0103n c\u1ee9"},
        {"doc_id": 99, "other_doc_id": 1, "relationship": "V\u0103n b\u1ea3n c\u0103n c\u1ee9"},
    ]

    graph = build_graph_tables(metadata_rows, relationship_rows)

    node_ids = {row["id"] for row in graph.nodes}
    assert {"doc:1", "doc:2", "legal_type:luat", "authority:quoc-hoi", "sector:thue"} <= node_ids

    doc_1 = next(row for row in graph.documents if row["id"] == "doc:1")
    assert doc_1["priority_tier"] == "unknown"
    assert doc_1["sector_list"] == "Thue|Phi"

    edge_types = {(row["source_id"], row["target_id"], row["type"]) for row in graph.edges}
    assert ("doc:2", "doc:1", "CITES") in edge_types
    assert ("doc:1", "legal_type:luat", "HAS_LEGAL_TYPE") in edge_types
    assert ("doc:1", "authority:quoc-hoi", "ISSUED_BY") in edge_types
    assert ("doc:1", "sector:thue", "IN_SECTOR") in edge_types
    assert graph.summary["orphan_document_relationship_edges"] == 1
    assert graph.summary["duplicate_node_ids"] == 0


def test_attaches_chunks_to_documents_without_double_prefixing_ids():
    from pipeline.graph.build_graph import build_graph_tables

    graph = build_graph_tables(
        metadata_rows=[
            {
                "id": 1,
                "document_number": "01/2026/QH",
                "title": "Luat kiem thu",
                "legal_type": "Luat",
                "legal_sectors": "Thue",
                "issuing_authority": "Quoc hoi",
                "issuance_date": "2026-01-01",
                "effect_status": "Con hieu luc",
                "source": "unit",
            }
        ],
        relationship_rows=[],
        chunk_rows=[
            {
                "chunk_id": "chunk:1:000001",
                "doc_id": 1,
                "chunk_type": "article",
                "section_path": ["Dieu 1"],
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
                "section_path": ["Dieu 2"],
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
    assert ("doc:1", "chunk:1:000001", "HAS_CHUNK") in edge_types
    assert ("chunk:1:000001", "chunk:1:000002", "NEXT_CHUNK") in edge_types
    assert ("chunk:1:000001", "chunk:1:000002", "PARENT_OF") in edge_types
    assert graph.summary["chunk_nodes"] == 2


def test_exports_graph_artifacts(tmp_path):
    from pipeline.graph.build_graph import build_graph_tables, export_graph_artifacts

    graph = build_graph_tables(
        metadata_rows=[
            {
                "id": 1,
                "document_number": "01/2026/QH",
                "title": "Luat kiem thu",
                "legal_type": "Luat",
                "legal_sectors": "Thue",
                "issuing_authority": "Quoc hoi",
                "issuance_date": "2026-01-01",
                "effect_status": "Con hieu luc",
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
    from pipeline.graph.build_graph import configure_stdout_for_utf8

    class FakeStdout:
        encoding = "cp1252"

        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    stdout = FakeStdout()
    configure_stdout_for_utf8(stdout)
    assert stdout.calls == [{"encoding": "utf-8"}]
