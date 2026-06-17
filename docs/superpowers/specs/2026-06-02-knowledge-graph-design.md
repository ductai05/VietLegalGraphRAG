# VietLegal Knowledge Graph Design

## Context

The current dataset in `data/preprocessed/` contains three cleaned Parquet files:

- `content.parquet`: document text with `id`, `content`, `source`.
- `metadata.parquet`: document catalog metadata with 353,746 rows.
- `relationships.parquet`: 138,656 document-level legal relationships.

The chunking pipeline in `pipeline/03_preprocessing/chunk.py` creates retrieval units with `doc_id`, `chunk_type`, `section_path`, `parent_id`, sequential links, and retrieval flags. The data is currently cleaned but not chunked, so graph construction must work before chunking and enrich itself when chunk artifacts are available.

## Goal

Build a reproducible Knowledge Graph construction pipeline for Vietnamese legal RAG that:

1. Builds document-level nodes and edges from cleaned metadata and relationships.
2. Accepts optional chunk output and attaches chunk nodes to documents.
3. Emits local graph artifacts that can be inspected without Neo4j.
4. Emits Neo4j import-ready CSV and Cypher loader files.
5. Uses stable identifiers so rerunning chunking or graph construction does not invalidate downstream vector, BM25, or graph indexes.

## Recommended Approach

Use an artifact-first KG pipeline:

- Generate canonical node and edge tables locally.
- Export CSV and JSONL artifacts under `data/graph/`.
- Generate Neo4j import Cypher under `pipeline/05_graph/neo4j_import.cypher`.
- Keep direct Neo4j loading optional, because no Neo4j connection settings are present in the repo.

This is preferred over a direct Neo4j-only build because it is testable on the current machine and does not hide graph quality problems behind a database import step. It is also preferred over a chunk-only graph because legal relationships are already present at document level and should remain a first-class KG layer.

## Graph Model

### Node Labels

`Document`

- Primary key: `doc:<id>`
- Source fields: `id`, `document_number`, `title`, `legal_type`, `legal_sectors`, `issuing_authority`, `issuance_date`, `effect_date`, `effectless_date`, `effect_status`, `signers`, `source`.
- Derived fields: `priority_tier`, `sector_list`.

`Chunk`

- Primary key: `chunk:<chunk_id>`
- Source fields: `chunk_id`, `doc_id`, `chunk_type`, `section_path`, `procedure_name`, `embed`, `keyword_index`, `token_estimate`, `quality_flags`.
- Optional source text fields are excluded from graph CSV by default to keep graph imports small. Retrieval systems should keep full text in vector and keyword indexes.

`LegalType`

- Primary key: `legal_type:<normalized_value>`.

`Authority`

- Primary key: `authority:<normalized_value>`.

`Sector`

- Primary key: `sector:<normalized_value>`.

### Edge Types

Document metadata edges:

- `HAS_LEGAL_TYPE`: `Document -> LegalType`
- `ISSUED_BY`: `Document -> Authority`
- `IN_SECTOR`: `Document -> Sector`

Document relationship edges from `relationships.parquet`:

- `CITES_AS_BASIS`: source document cites target document as basis.
- `CITES`: source document cites target document.
- `GUIDES_DETAIL`: source document guides or details target document.
- `IS_GUIDED_DETAILED_BY`: inverse guide/detail relation when the raw label says the source is the guided document.
- `AMENDS`: source document amends target document.
- `IS_AMENDED_BY`: inverse amendment relation when the raw label says the source is amended.
- `SUPPLEMENTS`: source document supplements target document.
- `IS_SUPPLEMENTED_BY`: inverse supplement relation when the raw label says the source is supplemented.
- `REPLACES_OR_EXPIRES`: source document makes target document wholly or partially ineffective.
- `IS_REPLACED_OR_EXPIRED_BY`: inverse effectiveness relation when the raw label says the source is affected.
- `SUSPENDS`: source document suspends target document.
- `IS_SUSPENDED_BY`: inverse suspension relation when the raw label says the source is suspended.
- `RELATED_TO`: low-confidence or miscellaneous relation.

Chunk edges:

- `HAS_CHUNK`: `Document -> Chunk`
- `NEXT_CHUNK`: `Chunk -> Chunk`
- `PARENT_OF`: `Chunk -> Chunk` only when parent chunk IDs can be resolved.

The chunker currently emits `parent_id` as a stable section hash, not as a chunk ID. The KG pipeline therefore records unresolved parent references in chunk properties and only emits `PARENT_OF` when both endpoints are known.

## Priority Tiers

The README describes three document priority layers. The KG pipeline encodes these as `priority_tier`:

- Tier 1: `Hiến pháp`, `Bộ luật`, `Luật`, `Pháp lệnh`, `Văn bản hợp nhất`.
- Tier 2: `Nghị định`, `Thông tư`, `Thông tư liên tịch`, `Quyết định`, `Nghị quyết`, `Chỉ thị`, `Hướng dẫn`.
- Tier 3: `Điều ước quốc tế`, `Hiệp định`, `Quy chế`, `Quy định`, `Văn bản WTO`, other specialized types.
- Unknown: missing or unrecognized legal type.

## Stable IDs

Chunk IDs must be deterministic. The chunker should emit chunk IDs using document ID plus zero-based chunk ordinal:

```text
chunk:<doc_id>:<000001>
```

The graph builder accepts existing chunk IDs but validates uniqueness. The chunker change is required because UUID chunk IDs break reproducibility across runs.

## Artifacts

Default output directory: `data/graph/`.

Required outputs:

- `nodes.csv`: all graph nodes.
- `edges.csv`: all graph edges.
- `documents.csv`: document node table for inspection.
- `document_relationship_edges.csv`: normalized document relationship edges.
- `graph_summary.json`: counts, relationship distribution, orphan edge counts, and validation flags.
- `neo4j_import.cypher`: generated loader for CSV import.

Optional outputs when chunks are available:

- `chunks.csv`: chunk node table.
- `chunk_edges.csv`: document to chunk and chunk sequential edges.

## Validation

The graph builder must report:

- Total document nodes.
- Total metadata dimension nodes.
- Total edges by type.
- Raw relationship labels that were normalized.
- Edges whose endpoints are missing from metadata.
- Duplicate node IDs.
- Duplicate edge IDs.
- Chunk rows missing `doc_id` or `chunk_id`.

Missing relationship endpoints are not fatal because relationships can reference filtered-out documents, but they must be counted and excluded from importable edges.

## Retrieval Use

The KG is used after retrieval to expand context:

1. Retrieve chunks with dense vector and BM25.
2. Map chunk hits to document nodes.
3. Expand within the document using `NEXT_CHUNK`, `HAS_CHUNK`, and available parent references.
4. Expand across documents through legal edges, with relation-type-specific limits.
5. Join metadata for citation and filtering.

This keeps the KG as a retrieval expansion and provenance layer, not as a replacement for vector or keyword retrieval.

