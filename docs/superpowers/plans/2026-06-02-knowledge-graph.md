# Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible Knowledge Graph construction pipeline for cleaned Vietnamese legal documents and optional chunk outputs.

**Architecture:** The implementation adds a focused graph construction package under `pipeline/05_graph/`. It builds canonical node and edge tables from Parquet inputs, exports local artifacts, and generates Neo4j import Cypher without requiring a running Neo4j instance.

**Tech Stack:** Python, pandas or pyarrow-backed Parquet readers, stdlib CSV and JSON, pytest, existing chunking module.

---

## File Structure

- Modify: `pipeline/03_preprocessing/chunk.py`
  - Make chunk IDs deterministic per document and chunk ordinal.
- Create: `pipeline/05_graph/__init__.py`
  - Package exports.
- Create: `pipeline/05_graph/schema.py`
  - Dataclasses and constants for node labels, edge types, priority tiers, and relationship normalization.
- Create: `pipeline/05_graph/build_graph.py`
  - Core graph builder and artifact exporter.
- Create: `pipeline/05_graph/run_graph_construction.py`
  - CLI entrypoint.
- Modify: `pipeline/05_graph/README.md`
  - Usage, artifacts, and Neo4j import notes.
- Create: `pipeline/05_graph/requirements.txt`
  - Runtime dependencies for graph construction.
- Create: `tests/test_chunking_stable_ids.py`
  - Verifies deterministic chunk IDs from the chunking pipeline.
- Create: `tests/test_knowledge_graph.py`
  - Verifies relation normalization, graph tables, validation, and artifact export.

## Tasks

### Task 1: Stable Chunk IDs

- [ ] Write a failing test in `tests/test_chunking_stable_ids.py` that chunks the same document twice and expects identical `chunk_id`, `prev_chunk_id`, and `next_chunk_id` values.
- [ ] Run `pytest tests/test_chunking_stable_ids.py -q` and verify it fails because IDs are random UUIDs.
- [ ] Modify `pipeline/03_preprocessing/chunk.py` so `_emit_chunk` uses a deterministic ID derived from `doc_id` and chunk ordinal.
- [ ] Run `pytest tests/test_chunking_stable_ids.py -q` and verify it passes.

### Task 2: Relationship Normalization

- [ ] Write a failing test in `tests/test_knowledge_graph.py` for normalizing all 15 raw relationship labels found in `relationships.parquet`.
- [ ] Run `pytest tests/test_knowledge_graph.py::test_normalizes_relationship_labels -q` and verify it fails because graph code does not exist.
- [ ] Implement `schema.py` with `normalize_relationship_label(raw_label)`.
- [ ] Run the relationship normalization test and verify it passes.

### Task 3: Document Graph Builder

- [ ] Write a failing test that builds graph tables from in-memory metadata and relationship rows.
- [ ] The test must assert document nodes, legal type nodes, authority nodes, sector nodes, and normalized edges exist.
- [ ] Run the test and verify it fails.
- [ ] Implement graph table construction in `build_graph.py`.
- [ ] Run the test and verify it passes.

### Task 4: Chunk Attachment

- [ ] Write a failing test that passes chunk rows and expects `Chunk` nodes plus `HAS_CHUNK` and `NEXT_CHUNK` edges.
- [ ] Run the test and verify it fails.
- [ ] Implement optional chunk loading and chunk edge creation.
- [ ] Run the test and verify it passes.

### Task 5: Artifact Export and CLI

- [ ] Write a failing test that exports graph artifacts to a temporary directory and verifies `nodes.csv`, `edges.csv`, `documents.csv`, `document_relationship_edges.csv`, `graph_summary.json`, and `neo4j_import.cypher`.
- [ ] Run the test and verify it fails.
- [ ] Implement CSV, JSON, and Cypher export in `build_graph.py`.
- [ ] Implement `run_graph_construction.py` with arguments for metadata, relationships, optional chunks, and output directory.
- [ ] Run the artifact export test and verify it passes.

### Task 6: Documentation and Sample Build

- [ ] Update `pipeline/05_graph/README.md` with KG model, commands, outputs, and Neo4j import sequence.
- [ ] Run unit tests.
- [ ] Run a sample graph build using current `data/preprocessed/metadata.parquet` and `relationships.parquet` with a small row limit.
- [ ] Inspect `graph_summary.json` and confirm counts and orphan edge reporting are plausible.

