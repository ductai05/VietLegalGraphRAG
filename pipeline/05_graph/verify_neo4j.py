#!/usr/bin/env python3
"""Standalone verification tool for the MVP Neo4j knowledge graph.

Inspects the database, counts objects, validates required labels and
relationship types, and checks ``raw_label`` preservation.  This script
is **read-only** — it never modifies data, creates schema, or performs
imports.

Usage::

    python pipeline/05_graph/verify_neo4j.py

Environment variables::

    NEO4J_URI        Bolt URI (default: bolt://localhost:7687)
    NEO4J_USER       Neo4j username (default: neo4j)
    NEO4J_PASSWORD   Neo4j password (default: password)
    NEO4J_DATABASE   Neo4j database name (default: neo4j)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

from neo4j import GraphDatabase


# ---------------------------------------------------------------------------
# Expected graph contracts (derived from pipeline/05_graph/schema.py)
# ---------------------------------------------------------------------------

REQUIRED_LABELS = {"Document", "Chunk"}

EXPECTED_LEGAL_RELATIONS = {"CITES", "AMENDS", "REPEALS", "GUIDELINES"}


# ---------------------------------------------------------------------------
# Report data structures
# ---------------------------------------------------------------------------


@dataclass
class VerificationReport:
    """Complete result of a Neo4j graph verification run."""

    connected: bool = False
    database: str = "unknown"
    version: str = "unknown"

    node_count: int = 0
    edge_count: int = 0
    document_count: int = 0
    chunk_count: int = 0

    labels_found: list[str] = field(default_factory=list)
    labels_missing: list[str] = field(default_factory=list)

    relationship_types_found: list[str] = field(default_factory=list)
    relationship_types_missing: list[str] = field(default_factory=list)

    raw_label_checked: int = 0
    raw_label_missing: int = 0

    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        """Passed if connected and no fatal errors (missing optional rels ok)."""
        return self.connected and len(self.errors) == 0

    def render(self) -> str:
        lines = ["Neo4j Verification", "=" * len("Neo4j Verification"), ""]

        status = "OK" if self.connected else "FAILED"
        lines.append(f"Connection: {status}")
        if not self.connected:
            for error in self.errors:
                lines.append(f"  Error: {error}")
            return "\n".join(lines)

        lines.append(f"Database: {self.database}")
        lines.append(f"Version:  {self.version}")
        lines.append(f"Nodes:    {self.node_count}")
        lines.append(f"Edges:    {self.edge_count}")
        lines.append(f"Documents: {self.document_count}")
        lines.append(f"Chunks:    {self.chunk_count}")
        lines.append("")

        # Labels
        lines.append("Labels:")
        for label in sorted(REQUIRED_LABELS):
            marker = "✓" if label in self.labels_found else "✗"
            lines.append(f"  {marker} {label}")
        for label in sorted(set(self.labels_found) - REQUIRED_LABELS):
            lines.append(f"    {label}")
        if self.labels_missing:
            lines.append("")
            for label in self.labels_missing:
                lines.append(f"  ✗ {label} REQUIRED — missing from database")
        lines.append("")

        # Relationships
        lines.append("Relationships:")
        for rel in sorted(EXPECTED_LEGAL_RELATIONS):
            if rel in self.relationship_types_found:
                lines.append(f"  ✓ {rel}")
            else:
                lines.append(f"  ⚠ {rel} missing")
        for rel in sorted(set(self.relationship_types_found) - EXPECTED_LEGAL_RELATIONS):
            lines.append(f"    {rel}")
        lines.append("")

        # raw_label (legal edges only)
        lines.append("raw_label (legal edges):")
        if self.raw_label_checked == 0:
            lines.append("  (no legal edges to inspect)")
        elif self.raw_label_missing == 0:
            lines.append(
                f"  ✓ all inspected legal edges preserved raw_label "
                f"({self.raw_label_checked} checked)"
            )
        else:
            missing_pct = int(self.raw_label_missing / self.raw_label_checked * 100)
            lines.append(
                f"  ⚠ {self.raw_label_missing}/{self.raw_label_checked} "
                f"legal edges ({missing_pct}%) missing raw_label"
            )
        lines.append("")

        # Warnings summary
        all_warnings = list(self.warnings)
        if self.relationship_types_missing:
            all_warnings.append(
                f"Missing optional relationship types: {', '.join(self.relationship_types_missing)}"
            )
        if self.raw_label_missing > 0:
            all_warnings.append(
                f"{self.raw_label_missing} legal edges missing raw_label"
            )

        if all_warnings:
            lines.append("Warnings:")
            for w in all_warnings:
                lines.append(f"  ⚠ {w}")
            lines.append("")

        if self.errors:
            lines.append("Errors:")
            for e in self.errors:
                lines.append(f"  ✗ {e}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core verification logic
# ---------------------------------------------------------------------------


def _get_env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _run_query(
    driver: Any, query: str, database: str, **params: Any
) -> list[Any]:
    """Execute a Cypher query and return all records."""
    with driver.session(database=database) as session:
        return list(session.run(query, **params))


def verify_neo4j(
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
) -> VerificationReport:
    """Run the full verification suite.

    Parameters are read from environment variables by default but can be
    overridden for testing.
    """
    resolved_uri = uri or _get_env("NEO4J_URI", "bolt://localhost:7687")
    resolved_user = user or _get_env("NEO4J_USER", "neo4j")
    resolved_password = password or _get_env("NEO4J_PASSWORD", "password")
    resolved_database = database or _get_env("NEO4J_DATABASE", "neo4j")

    report = VerificationReport(database=resolved_database)

    # ------------------------------------------------------------------
    # 1. Connect
    # ------------------------------------------------------------------
    try:
        driver = GraphDatabase.driver(
            resolved_uri,
            auth=(resolved_user, resolved_password),
        )
        driver.verify_connectivity()
        report.connected = True
    except Exception as exc:
        report.connected = False
        report.errors.append(f"Cannot connect to Neo4j: {exc}")
        return report

    try:
        # --------------------------------------------------------------
        # 2. Version
        # --------------------------------------------------------------
        try:
            records = _run_query(
                driver,
                "CALL dbms.components() YIELD versions RETURN versions[0] AS version",
                resolved_database,
            )
            if records:
                report.version = records[0].get("version", "unknown")
        except Exception:
            report.warnings.append("Could not determine Neo4j version")

        # --------------------------------------------------------------
        # 3. Count graph objects
        # --------------------------------------------------------------
        try:
            records = _run_query(
                driver,
                "MATCH (n) RETURN count(n) AS cnt",
                resolved_database,
            )
            if records:
                report.node_count = records[0].get("cnt", 0)
        except Exception as exc:
            report.errors.append(f"Node count query failed: {exc}")

        try:
            records = _run_query(
                driver,
                "MATCH ()-[r]->() RETURN count(r) AS cnt",
                resolved_database,
            )
            if records:
                report.edge_count = records[0].get("cnt", 0)
        except Exception as exc:
            report.errors.append(f"Edge count query failed: {exc}")

        try:
            records = _run_query(
                driver,
                "MATCH (d:Document) RETURN count(d) AS cnt",
                resolved_database,
            )
            if records:
                report.document_count = records[0].get("cnt", 0)
        except Exception as exc:
            report.errors.append(f"Document count query failed: {exc}")

        try:
            records = _run_query(
                driver,
                "MATCH (c:Chunk) RETURN count(c) AS cnt",
                resolved_database,
            )
            if records:
                report.chunk_count = records[0].get("cnt", 0)
        except Exception as exc:
            report.errors.append(f"Chunk count query failed: {exc}")

        # --------------------------------------------------------------
        # 4. Verify required labels  (fatal if missing)
        # --------------------------------------------------------------
        try:
            records = _run_query(
                driver,
                "CALL db.labels() YIELD label RETURN collect(label) AS labels",
                resolved_database,
            )
            if records:
                report.labels_found = sorted(records[0].get("labels", []))
        except Exception as exc:
            report.errors.append(f"Label check query failed: {exc}")

        report.labels_missing = sorted(
            set(REQUIRED_LABELS) - set(report.labels_found)
        )
        if report.labels_missing:
            for label in report.labels_missing:
                report.errors.append(
                    f"Required label '{label}' is missing from the database"
                )

        # --------------------------------------------------------------
        # 5. Verify relationship types  (optional — warnings only)
        # --------------------------------------------------------------
        try:
            records = _run_query(
                driver,
                "CALL db.relationshipTypes() YIELD relationshipType "
                "RETURN collect(relationshipType) AS types",
                resolved_database,
            )
            if records:
                report.relationship_types_found = sorted(
                    records[0].get("types", [])
                )
        except Exception as exc:
            report.errors.append(f"Relationship type query failed: {exc}")

        report.relationship_types_missing = sorted(
            set(EXPECTED_LEGAL_RELATIONS)
            - set(report.relationship_types_found)
        )

        # --------------------------------------------------------------
        # 6. Verify raw_label preservation (legal edges only)
        # --------------------------------------------------------------
        legal_types_list = list(EXPECTED_LEGAL_RELATIONS)
        try:
            # Count legal edges first
            legal_records = _run_query(
                driver,
                "MATCH ()-[r]->() WHERE type(r) IN $legal_types "
                "RETURN count(r) AS cnt",
                resolved_database,
                legal_types=legal_types_list,
            )
            legal_edge_count = legal_records[0].get("cnt", 0) if legal_records else 0

            if legal_edge_count > 0:
                report.raw_label_checked = legal_edge_count
                raw_label_records = _run_query(
                    driver,
                    "MATCH ()-[r]->() "
                    "WHERE type(r) IN $legal_types "
                    "AND r.raw_label IS NOT NULL AND trim(r.raw_label) <> '' "
                    "RETURN count(r) AS with_label "
                    "UNION ALL "
                    "MATCH ()-[r]->() "
                    "WHERE type(r) IN $legal_types "
                    "AND (r.raw_label IS NULL OR trim(r.raw_label) = '') "
                    "RETURN count(r) AS without_label",
                    resolved_database,
                    legal_types=legal_types_list,
                )
                # UNION ALL produces two rows: with_label, then without_label
                for rec in raw_label_records:
                    if rec.get("without_label", 0) > 0:
                        report.raw_label_missing = rec["without_label"]
        except Exception as exc:
            report.errors.append(f"raw_label check query failed: {exc}")

    finally:
        driver.close()

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run verification and print the report to stdout."""
    report = verify_neo4j()
    print(report.render())

    if report.healthy:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
