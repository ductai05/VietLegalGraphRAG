# KG Progress Audit

Generated at: `2026-06-18 00:12:46`

## What Was Checked

- Existing Neo4j bulk-import CSVs under `data/processed/neo4j_imports`.
- Import report warnings from `import.report`.
- Current retrieval error cases under `output/report_artifacts/retrieval_error_cases.json`.

## Graph Size From CSV Export

| Node label | Rows |
| --- | --- |
| Document | 353,665 |
| Article | 7,476,806 |
| LegalType | 37 |
| Authority | 1,758 |
| Sector | 1,582 |

| Relationship group | Rows |
| --- | --- |
| Document-Document | 122,144 |
| Document-Article | 7,476,806 |
| Article-NEXT | 7,123,141 |
| Article-PARENT | 3,971,734 |
| Document-LegalType | 353,663 |
| Document-Authority | 353,455 |
| Document-Sector | 593,901 |

Total nodes from CSV: **7,833,848**
Total relationships from CSV: **19,994,844**

## Document-Document Relationship Types

| Type | Rows |
| --- | --- |
| AMENDS | 4,291 |
| CITES | 117,839 |
| REPEALS | 14 |

## Import Report Health

- Duplicate metadata warnings: **142**.
- Duplicate groups: `{'Authority': 98, 'Sector': 44}`.
- These are metadata node duplicates tolerated by the current import script via `--skip-duplicate-nodes=true`; they do not invalidate Document/Article rows, but the metadata export should be deduplicated later.

## Link To Current Retrieval Evaluation

For the 10 sampled Hybrid+Rerank misses, the audit maps gold/top-3 chunk UUIDs back to Article and Document IDs in the KG export.

| Question | Group | Gold docs | Top-3 docs | Same doc | Direct KG doc bridge |
| --- | --- | --- | --- | --- | --- |
| q_010 | factual | 521106 | 521106, 525474, 528689 | 521106 | - |
| q_012 | inference | 521106 | 465310, 523937, 7212 | - | - |
| q_016 | inference | 37973 | 13673, 224226, 300127 | - | - |
| q_026 | procedural | 381687 | 385879, 389880, 391131 | - | - |
| q_031 | factual | 448304 | 426144, 478066, 516320 | - | - |
| q_041 | factual | 519424 | 348562, 348563, 496749 | - | - |
| q_047 | comparison | 5871 | 130343, 21519, 48009 | - | - |
| q_064 | procedural | 365822 | 438090, 498190, 575160 | - | - |
| q_066 | procedural | 411573 | 553768, 689420, 689894 | - | - |
| q_079 | comparison | 413044 | 414074, 556519, 681160 | - | - |

- Error cases checked: **10**
- Error cases whose chunks mapped to KG export: **10**
- Error cases where top-3 already contains the gold document: **1**
- Direct Document-Document bridges between top-3 retrieved docs and gold docs: **0**

## Immediate Takeaway

KG assets are still usable: the full Neo4j import CSV export exists locally and covers the current retrieval evaluation chunks. As an immediate next step, KG can be used for error analysis and query expansion around retrieved/gold documents, without waiting for embeddings to be stored inside Neo4j.
