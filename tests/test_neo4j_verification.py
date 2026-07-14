"""Tests for pipeline/05_graph/verify_neo4j.py.

All tests use mocked Neo4j drivers — no running Neo4j instance required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("neo4j")

from verify_neo4j import (  # noqa: E402
    EXPECTED_LEGAL_RELATIONS,
    REQUIRED_LABELS,
    VerificationReport,
    main,
    verify_neo4j,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class FakeRecord(dict):
    """A record that supports dict-like access (matching neo4j.Record)."""

    def get(self, key, default=None):
        return dict.__getitem__(self, key) if key in self else default


class FakeSession:
    """Configurable fake Neo4j session whose run() returns preloaded records."""

    def __init__(self, records_by_query: dict[str, list[FakeRecord]] | None = None):
        self.calls: list[tuple[str, dict]] = []
        self._records = records_by_query or {}

    def run(self, query: str, **params):
        self.calls.append((query, params))
        return self._records.get(query, [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeDriver:
    """Fake Neo4j driver that returns a preconfigured FakeSession."""

    def __init__(self, session: FakeSession, connectivity: bool = True):
        self._session = session
        self._connectivity = connectivity
        self.closed = False

    def verify_connectivity(self):
        if not self._connectivity:
            raise OSError("Connection refused")
        return None

    def session(self, database: str | None = None):
        return self._session

    def close(self):
        self.closed = True


def _query_key(query: str) -> str:
    """Normalize a query for dict lookup (strip leading/trailing whitespace)."""
    return query.strip()


# ---------------------------------------------------------------------------
# Helpers to build healthy mock records
# ---------------------------------------------------------------------------

_LEGAL_TYPES_LIST = list(EXPECTED_LEGAL_RELATIONS)


def _make_raw_label_with_count(
    total_legal: int, missing_count: int = 0
) -> dict[str, list[FakeRecord]]:
    """Build the raw_label query responses.

    The script runs two queries:
      1. COUNT of legal-type edges.
      2. UNION ALL: with_label and without_label counts.
    """
    present = total_legal - missing_count
    query1 = (
        "MATCH ()-[r]->() WHERE type(r) IN $legal_types "
        "RETURN count(r) AS cnt"
    )
    query2 = (
        "MATCH ()-[r]->() "
        "WHERE type(r) IN $legal_types "
        "AND r.raw_label IS NOT NULL AND trim(r.raw_label) <> '' "
        "RETURN count(r) AS with_label "
        "UNION ALL "
        "MATCH ()-[r]->() "
        "WHERE type(r) IN $legal_types "
        "AND (r.raw_label IS NULL OR trim(r.raw_label) = '') "
        "RETURN count(r) AS without_label"
    )
    return {
        query1: [FakeRecord({"cnt": total_legal})],
        query2: [
            FakeRecord({"with_label": present}),
            FakeRecord({"without_label": missing_count}),
        ],
    }


def _common_records() -> dict[str, list[FakeRecord]]:
    return {
        "CALL dbms.components() YIELD versions RETURN versions[0] AS version": [
            FakeRecord({"version": "5.26.0"})
        ],
        "MATCH (n) RETURN count(n) AS cnt": [FakeRecord({"cnt": 100})],
        "MATCH ()-[r]->() RETURN count(r) AS cnt": [FakeRecord({"cnt": 57})],
        "MATCH (d:Document) RETURN count(d) AS cnt": [
            FakeRecord({"cnt": 10})
        ],
        "MATCH (c:Chunk) RETURN count(c) AS cnt": [FakeRecord({"cnt": 20})],
        "CALL db.labels() YIELD label RETURN collect(label) AS labels": [
            FakeRecord(
                {
                    "labels": [
                        "Document",
                        "Chunk",
                        "LegalType",
                        "Authority",
                        "Sector",
                    ]
                }
            )
        ],
        "CALL db.relationshipTypes() YIELD relationshipType "
        "RETURN collect(relationshipType) AS types": [
            FakeRecord(
                {
                    "types": [
                        "AMENDS",
                        "CITES",
                        "GUIDELINES",
                        "HAS_CHUNK",
                        "REPEALS",
                    ]
                }
            )
        ],
    }


def _make_healthy_records() -> dict[str, list[FakeRecord]]:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=40, missing_count=0))
    return records


def _make_healthy_driver() -> FakeDriver:
    return FakeDriver(FakeSession(_make_healthy_records()))


# ---------------------------------------------------------------------------
# Tests: successful verification
# ---------------------------------------------------------------------------


def test_verify_healthy_database_reports_connected() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = _make_healthy_driver()
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.connected is True
    assert report.healthy is True
    assert report.database == "neo4j"


def test_verify_healthy_database_reports_version() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = _make_healthy_driver()
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.version == "5.26.0"


def test_verify_healthy_database_reports_node_and_edge_counts() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = _make_healthy_driver()
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.node_count == 100
    assert report.edge_count == 57
    assert report.document_count == 10
    assert report.chunk_count == 20


def test_verify_healthy_database_reports_required_labels_present() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = _make_healthy_driver()
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    for label in REQUIRED_LABELS:
        assert label in report.labels_found
    assert report.labels_missing == []


def test_verify_healthy_database_reports_all_legal_relations() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = _make_healthy_driver()
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    for rel in EXPECTED_LEGAL_RELATIONS:
        assert rel in report.relationship_types_found
    assert report.relationship_types_missing == []


def test_raw_label_all_present_reports_zero_missing() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = _make_healthy_driver()
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.raw_label_checked == 40
    assert report.raw_label_missing == 0


def test_render_healthy_report_contains_key_terms() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = _make_healthy_driver()
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    rendered = report.render()
    assert "Connection: OK" in rendered
    assert "Database: neo4j" in rendered
    assert "Nodes:    100" in rendered
    assert "Edges:    57" in rendered
    assert "Documents: 10" in rendered
    assert "Chunks:    20" in rendered
    assert "✓ Document" in rendered
    assert "✓ Chunk" in rendered
    assert "✓ AMENDS" in rendered
    assert "✓ CITES" in rendered
    assert "✓ REPEALS" in rendered
    assert "✓ GUIDELINES" in rendered
    assert "all inspected legal edges preserved raw_label" in rendered


# ---------------------------------------------------------------------------
# Tests: connection failure
# ---------------------------------------------------------------------------


def test_connection_failure_reports_not_connected() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(
            FakeSession(), connectivity=False
        )
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="bad",
            database="neo4j",
        )

    assert report.connected is False
    assert report.healthy is False
    assert len(report.errors) >= 1
    assert "Cannot connect" in report.errors[0]


def test_connection_failure_report_render_shows_failed() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(
            FakeSession(), connectivity=False
        )
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="bad",
            database="neo4j",
        )

    rendered = report.render()
    assert "Connection: FAILED" in rendered


# ---------------------------------------------------------------------------
# Tests: missing required labels are FATAL
# ---------------------------------------------------------------------------


def test_missing_document_label_causes_unhealthy() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=0))
    # Only Chunk, not Document
    records[
        "CALL db.labels() YIELD label RETURN collect(label) AS labels"
    ] = [FakeRecord({"labels": ["Chunk"]})]

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert "Document" in report.labels_missing
    assert report.healthy is False
    assert any("Document" in e for e in report.errors)


def test_missing_chunk_label_causes_unhealthy() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=0))
    # Only Document, not Chunk
    records[
        "CALL db.labels() YIELD label RETURN collect(label) AS labels"
    ] = [FakeRecord({"labels": ["Document"]})]

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert "Chunk" in report.labels_missing
    assert report.healthy is False
    assert any("Chunk" in e for e in report.errors)


def test_missing_both_required_labels_causes_unhealthy() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=0))
    # Neither Document nor Chunk
    records[
        "CALL db.labels() YIELD label RETURN collect(label) AS labels"
    ] = [FakeRecord({"labels": ["LegalType", "Sector"]})]

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert "Document" in report.labels_missing
    assert "Chunk" in report.labels_missing
    assert report.healthy is False
    # Should have two error entries — one per missing required label
    error_labels = [
        e for e in report.errors if "Required label" in e
    ]
    assert len(error_labels) == 2


# ---------------------------------------------------------------------------
# Tests: missing relationship type (warning, not failure)
# ---------------------------------------------------------------------------


def test_missing_relationship_type_is_warning_not_error() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=20))
    # Only CITES and AMENDS — REPEALS and GUIDELINES are absent
    records[
        "CALL db.relationshipTypes() YIELD relationshipType "
        "RETURN collect(relationshipType) AS types"
    ] = [FakeRecord({"types": ["CITES", "AMENDS", "HAS_CHUNK"]})]

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert "CITES" in report.relationship_types_found
    assert "AMENDS" in report.relationship_types_found
    assert "REPEALS" in report.relationship_types_missing
    assert "GUIDELINES" in report.relationship_types_missing
    # Must NOT be an error — missing optional types should not fail
    assert report.errors == []
    assert report.healthy is True


def test_render_shows_missing_relationship_with_warning_symbol() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=20))
    records[
        "CALL db.relationshipTypes() YIELD relationshipType "
        "RETURN collect(relationshipType) AS types"
    ] = [FakeRecord({"types": ["CITES"]})]

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    rendered = report.render()
    assert "✓ CITES" in rendered
    assert "⚠ AMENDS missing" in rendered
    assert "⚠ REPEALS missing" in rendered
    assert "⚠ GUIDELINES missing" in rendered
    assert "Missing optional relationship types" in rendered


# ---------------------------------------------------------------------------
# Tests: raw_label verification (legal edges only)
# ---------------------------------------------------------------------------


def test_missing_raw_label_produces_warning() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=100, missing_count=10))

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.raw_label_checked == 100
    assert report.raw_label_missing == 10
    # raw_label missing is a warning, not an error
    assert report.errors == []
    assert report.healthy is True


def test_render_shows_raw_label_warning() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=100, missing_count=10))

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    rendered = report.render()
    assert "10/100 legal edges (10%) missing raw_label" in rendered


def test_raw_label_ignores_non_legal_edge_has_chunk() -> None:
    """HAS_CHUNK edges must NOT be counted in raw_label verification."""
    records = _common_records()
    # Total edges = 50 legal + 200 HAS_CHUNK = 250
    records["MATCH ()-[r]->() RETURN count(r) AS cnt"] = [
        FakeRecord({"cnt": 250})
    ]
    # All 50 legal edges have raw_label; HAS_CHUNK has no raw_label but
    # must not be counted
    records.update(_make_raw_label_with_count(total_legal=50, missing_count=0))

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.edge_count == 250
    assert report.raw_label_checked == 50
    assert report.raw_label_missing == 0


def test_raw_label_ignores_other_non_legal_edges() -> None:
    """Non-legal edges like HAS_METADATA must NOT be counted."""
    records = _common_records()
    records["MATCH ()-[r]->() RETURN count(r) AS cnt"] = [
        FakeRecord({"cnt": 300})
    ]
    records.update(_make_raw_label_with_count(total_legal=30, missing_count=0))

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.edge_count == 300
    assert report.raw_label_checked == 30


def test_whitespace_only_raw_label_treated_as_missing() -> None:
    """raw_label with only whitespace counts the same as NULL."""
    records = _common_records()
    records.update(
        _make_raw_label_with_count(total_legal=50, missing_count=5)
    )

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    # The script already uses trim(r.raw_label) <> '' to treat
    # whitespace-only as missing — verify the aggregate test passes
    assert report.raw_label_checked == 50
    assert report.raw_label_missing == 5


# ---------------------------------------------------------------------------
# Tests: zero legal edges — raw_label check gracefully skipped
# ---------------------------------------------------------------------------


def test_zero_legal_edges_skips_raw_label_check() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=0, missing_count=0))

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.raw_label_checked == 0
    assert "(no legal edges to inspect)" in report.render()


# ---------------------------------------------------------------------------
# Tests: query failure (error, not crash)
# ---------------------------------------------------------------------------


def test_query_failure_produces_error_not_exception() -> None:
    class BrokenSession(FakeSession):
        def run(self, query, **params):
            self.calls.append((query, params))
            if "MATCH (n)" in query:  # node count query
                raise RuntimeError("Database is down")
            return []

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(BrokenSession())
        report = verify_neo4j(
            uri="bolt://fake:7687",
            user="neo4j",
            password="pass",
            database="neo4j",
        )

    assert report.errors  # should have at least one error
    assert any(
        "Node count query failed" in e or "Database is down" in e
        for e in report.errors
    )
    # Still connected — verify_connectivity succeeded
    assert report.connected is True


# ---------------------------------------------------------------------------
# Tests: exit code semantics
# ---------------------------------------------------------------------------


def test_healthy_report_healthy_is_true() -> None:
    report = VerificationReport(connected=True)
    assert report.healthy is True


def test_disconnected_report_healthy_is_false() -> None:
    report = VerificationReport(connected=False)
    report.errors.append("Cannot connect")
    assert report.healthy is False


def test_missing_optional_relationship_does_not_block_healthy() -> None:
    report = VerificationReport(connected=True)
    report.relationship_types_missing = ["REPEALS"]
    report.warnings.append("Missing optional relationship types: REPEALS")
    assert report.healthy is True


def test_main_returns_zero_on_healthy_verification() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = _make_healthy_driver()
        exit_code = main()

    assert exit_code == 0


def test_main_returns_nonzero_on_connection_failure() -> None:
    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(
            FakeSession(), connectivity=False
        )
        exit_code = main()

    assert exit_code != 0


def test_main_returns_nonzero_on_missing_required_label() -> None:
    records = _common_records()
    records.update(_make_raw_label_with_count(total_legal=0))
    records[
        "CALL db.labels() YIELD label RETURN collect(label) AS labels"
    ] = [FakeRecord({"labels": []})]

    with patch("verify_neo4j.GraphDatabase") as mock_db:
        mock_db.driver.return_value = FakeDriver(FakeSession(records))
        exit_code = main()

    assert exit_code != 0
