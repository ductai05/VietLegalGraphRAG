# MVP Backend KG Infra Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P0/P1 MVP foundation for VietLegalGraphRAG: KG audit/import readiness, Elasticsearch-only retrieval service, GraphRetriever, LightRAG orchestration, FastAPI API, frontend API contract, Docker Compose skeleton and evaluation hooks.

**Architecture:** The implementation keeps pipeline code as data preparation utilities and places runtime services under `src/backend`. FastAPI depends on service interfaces, not pipeline internals. Neo4j provides graph context, Elasticsearch provides dense and sparse retrieval, and LightRAGService merges retrieval, graph and answer contexts.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, Elasticsearch, Neo4j Python driver, pytest, Docker Compose, PowerShell helper scripts.

---

## Scope

This plan covers the first implementation pass for:

- Phase 0: scope baseline and env docs.
- Phase 1: KG audit and artifact quality report.
- Phase 2: Neo4j import verification path.
- Phase 3: retrieval service consolidation.
- Phase 4: GraphRetriever.
- Phase 5: LightRAG runtime orchestration.
- Phase 6a and 6b: FastAPI search, answer and graph endpoints.
- Phase 7: frontend API contract.
- Phase 8: graph evaluation hooks.
- Phase 10: Docker Compose skeleton.

This plan does not implement production CI/CD, monitoring, full cloud deployment, incremental updates or stress testing.

## File Structure

Create or modify these files:

- `src/backend/services/contracts.py`: shared dataclasses for `RetrievalHit`, `GraphContext`, `AnswerContext`, `ServiceWarning` and error payloads.
- `src/backend/services/retrieval_modes.py`: keep existing request config, add conversion helpers if needed.
- `src/backend/services/retrieval_service.py`: service facade for dense, sparse, hybrid and rerank execution modes.
- `src/backend/services/rerank_service.py`: reranker protocol and deterministic fallback reranker for tests.
- `src/backend/services/graph_retriever.py`: Neo4j graph access and graph context shaping.
- `src/backend/services/intent_detector.py`: rule-based legal intent detection.
- `src/backend/services/context_assembler.py`: merge and deduplicate retrieval and graph contexts.
- `src/backend/services/answer_service.py`: answer service protocol and simple extractive/dev answer implementation.
- `src/backend/services/lightrag_service.py`: update to use contracts and context assembler.
- `src/backend/app/config.py`: env-based backend config.
- `src/backend/app/schemas.py`: Pydantic request and response schemas.
- `src/backend/app/dependencies.py`: dependency factory for app services.
- `src/backend/app/main.py`: FastAPI app factory and route registration.
- `src/backend/app/routes/health.py`: health endpoint.
- `src/backend/app/routes/search.py`: search and answer endpoints.
- `src/backend/app/routes/documents.py`: graph and version-chain endpoints.
- `pipeline/05_graph/audit_graph_artifacts.py`: artifact-level KG quality report.
- `pipeline/05_graph/verify_neo4j.py`: Neo4j count and sample query verification.
- `pipeline/07_evaluation/evaluate_graph.py`: graph-specific evaluation hooks.
- `src/frontend/API_CONTRACT.md`: handoff contract for FE.
- `src/frontend/mocks/search_response.json`: mock search response.
- `src/frontend/mocks/answer_response.json`: mock answer response.
- `.env.example`: root environment template.
- `src/infra/.env.example`: Docker Compose environment template.
- `src/infra/docker-compose.yml`: demo services.
- `src/backend/Dockerfile`: API container.
- Tests under `tests/`.

## Task 1: Baseline Env and Scope Docs

**Files:**
- Create: `.env.example`
- Modify: `README.md`
- Modify: `src/backend/README.md`
- Modify: `src/infra/README.md`

- [ ] **Step 1: Add env template**

Create `.env.example` with:

```dotenv
ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_API_KEY=
ELASTICSEARCH_DENSE_INDEX=vietlegal_dense
ELASTICSEARCH_SPARSE_INDEX=vietlegal_sparse

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j

LLM_PROVIDER=mock
LLM_API_KEY=
DEFAULT_RETRIEVAL_MODE=hybrid
DEFAULT_TEMPERATURE=0.2

RERANK_MODEL=BAAI/bge-reranker-v2-m3
RERANK_DEVICE=auto
RERANK_TIMEOUT_MS=30000

BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
FRONTEND_ORIGIN=http://localhost:5173
```

- [ ] **Step 2: Update README MVP scope**

Add this section near the project overview in `README.md`:

```markdown
## MVP Runtime Scope

The MVP runtime uses Elasticsearch for both dense and sparse retrieval, Neo4j for the legal knowledge graph, and FastAPI for the backend contract consumed by the frontend.

Qdrant references in older embedding notes are historical and are not required for the MVP runtime. Frontend code should call the backend API only and should not call Elasticsearch, Neo4j, reranker models or LLM providers directly.
```

- [ ] **Step 3: Update backend README**

Add this section to `src/backend/README.md`:

```markdown
## Runtime Services

- `services/retrieval_service.py`: resolves dense, sparse, hybrid and rerank execution modes.
- `services/graph_retriever.py`: reads legal graph context from Neo4j.
- `services/lightrag_service.py`: orchestrates retrieval, graph expansion and answer generation.
- `app/`: FastAPI application, request schemas and routes.
```

- [ ] **Step 4: Update infra README**

Add this section to `src/infra/README.md`:

```markdown
## Demo Stack

The demo stack contains FastAPI, Elasticsearch and Neo4j. Full-corpus graph import may exceed small local machines, so keep a subset graph path available for class demo.
```

- [ ] **Step 5: Verify docs and commit**

Run:

```powershell
git diff --check -- .env.example README.md src/backend/README.md src/infra/README.md
```

Expected: no output.

Commit:

```powershell
git add .env.example README.md src/backend/README.md src/infra/README.md
git commit -m "docs: define MVP runtime scope"
```

## Task 2: Shared Service Contracts

**Files:**
- Create: `src/backend/services/contracts.py`
- Test: `tests/test_service_contracts.py`

- [ ] **Step 1: Write contract tests**

Create `tests/test_service_contracts.py`:

```python
from contracts import (
    AnswerContext,
    GraphContext,
    GraphEdge,
    GraphNode,
    RetrievalHit,
)


def test_retrieval_hit_has_stable_score_keys():
    hit = RetrievalHit(
        rank=1,
        chunk_id="chunk:1:000001",
        doc_id="1",
        title="Luat xay dung",
        document_number="50/2014/QH13",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 89",
        text="Noi dung",
        scores={"dense": 0.8, "sparse": 12.0, "rrf": 0.03, "rerank": 0.7},
        citation="Luat xay dung, Dieu 89",
    )

    assert hit.to_dict()["scores"]["rrf"] == 0.03
    assert hit.to_answer_context().source == "retrieval"


def test_graph_context_serializes_edges_with_raw_label():
    context = GraphContext(
        center=GraphNode(id="doc:1", label="Document", properties={"doc_id": "1"}),
        nodes=[GraphNode(id="doc:1", label="Document", properties={"doc_id": "1"})],
        edges=[
            GraphEdge(
                source="doc:2",
                target="doc:1",
                type="AMENDS",
                raw_label="Van ban duoc sua doi",
                direction="in",
            )
        ],
        related_chunks=[],
        query_intent="amendment",
    )

    payload = context.to_dict()
    assert payload["edges"][0]["raw_label"] == "Van ban duoc sua doi"
    assert payload["query_intent"] == "amendment"


def test_answer_context_accepts_graph_source():
    item = AnswerContext(
        source="graph",
        chunk_id=None,
        doc_id="2",
        title="Nghi dinh",
        text="Graph evidence",
        citation="Nghi dinh",
        relation="CITES",
        raw_label="Van ban can cu",
    )

    assert item.to_dict()["source"] == "graph"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_service_contracts.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'contracts'`.

- [ ] **Step 3: Implement contracts**

Create `src/backend/services/contracts.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


ContextSource = Literal["retrieval", "graph"]


@dataclass
class AnswerContext:
    source: ContextSource
    chunk_id: str | None
    doc_id: str
    title: str
    text: str
    citation: str
    relation: str | None = None
    raw_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalHit:
    rank: int
    chunk_id: str
    doc_id: str
    title: str
    document_number: str
    legal_type: str
    effect_status: str
    section_path: str
    text: str
    scores: dict[str, float] = field(default_factory=dict)
    citation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_answer_context(self) -> AnswerContext:
        return AnswerContext(
            source="retrieval",
            chunk_id=self.chunk_id,
            doc_id=self.doc_id,
            title=self.title,
            text=self.text,
            citation=self.citation,
        )


@dataclass
class GraphNode:
    id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    source: str
    target: str
    type: str
    raw_label: str
    direction: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphContext:
    center: GraphNode | None
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    related_chunks: list[AnswerContext] = field(default_factory=list)
    query_intent: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "center": self.center.to_dict() if self.center else None,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "related_chunks": [chunk.to_dict() for chunk in self.related_chunks],
            "query_intent": self.query_intent,
        }


@dataclass
class ServiceWarning:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
```

- [ ] **Step 4: Run contract tests**

Run:

```powershell
pytest tests/test_service_contracts.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/backend/services/contracts.py tests/test_service_contracts.py
git commit -m "feat: add backend service contracts"
```

## Task 3: KG Artifact Audit Script

**Files:**
- Create: `pipeline/05_graph/audit_graph_artifacts.py`
- Test: `tests/test_kg_artifact_audit.py`

- [ ] **Step 1: Write failing audit tests**

Create `tests/test_kg_artifact_audit.py`:

```python
import csv
import json
from pathlib import Path

from audit_graph_artifacts import audit_graph_artifacts


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_audit_graph_artifacts_reports_mvp_invariants(tmp_path):
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


def test_audit_graph_artifacts_writes_report(tmp_path):
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

    report_json = json.loads((tmp_path / "report" / "kg_quality_summary.json").read_text(encoding="utf-8"))
    report_md = (tmp_path / "report" / "kg_quality_report.md").read_text(encoding="utf-8")
    assert report_json["self_loop_edges"] == 1
    assert summary["edges_missing_raw_label"] == 1
    assert "KG Quality Report" in report_md
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_kg_artifact_audit.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'audit_graph_artifacts'`.

- [ ] **Step 3: Implement audit script**

Create `pipeline/05_graph/audit_graph_artifacts.py`:

```python
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


CANONICAL_RELATIONS = {"AMENDS", "CITES", "REPEALS", "GUIDELINES"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def audit_graph_artifacts(
    artifact_dir: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_path = Path(artifact_dir)
    documents = read_csv(artifact_path / "documents.csv")
    edges = read_csv(artifact_path / "document_relationship_edges.csv")
    chunks = read_csv(artifact_path / "chunks.csv")

    document_ids = {row.get("id", "") for row in documents}
    document_id_counts = Counter(row.get("id", "") for row in documents)
    chunk_id_counts = Counter(row.get("id", "") for row in chunks)

    missing_endpoint_edges = 0
    self_loop_edges = 0
    edges_missing_raw_label = 0
    unknown_relation_count = 0
    edge_type_counts: Counter[str] = Counter()

    for edge in edges:
        source = edge.get("source_id", "")
        target = edge.get("target_id", "")
        edge_type = edge.get("type", "")
        edge_type_counts[edge_type] += 1
        if source not in document_ids or target not in document_ids:
            missing_endpoint_edges += 1
        if source == target:
            self_loop_edges += 1
        if not edge.get("raw_label", "").strip():
            edges_missing_raw_label += 1
        if edge_type not in CANONICAL_RELATIONS:
            unknown_relation_count += 1

    summary = {
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "document_relationship_count": len(edges),
        "missing_endpoint_edges": missing_endpoint_edges,
        "self_loop_edges": self_loop_edges,
        "edges_missing_raw_label": edges_missing_raw_label,
        "unknown_canonical_relation_count": unknown_relation_count,
        "duplicate_document_ids": sum(1 for value in document_id_counts.values() if value > 1),
        "duplicate_article_or_chunk_ids": sum(1 for value in chunk_id_counts.values() if value > 1),
        "edge_type_counts": dict(sorted(edge_type_counts.items())),
    }

    if output_dir is not None:
        write_report(summary, Path(output_dir))

    return summary


def write_report(summary: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "kg_quality_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        "# KG Quality Report",
        "",
        f"- Documents: {summary['document_count']}",
        f"- Chunks: {summary['chunk_count']}",
        f"- Document relationships: {summary['document_relationship_count']}",
        f"- Missing endpoint edges: {summary['missing_endpoint_edges']}",
        f"- Self-loop edges: {summary['self_loop_edges']}",
        f"- Edges missing raw_label: {summary['edges_missing_raw_label']}",
        f"- Unknown canonical relations: {summary['unknown_canonical_relation_count']}",
    ]
    (output_dir / "kg_quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit KG CSV artifacts for MVP invariants.")
    parser.add_argument("--artifact-dir", default="data/graph")
    parser.add_argument("--output-dir", default="output/kg_quality")
    args = parser.parse_args()
    summary = audit_graph_artifacts(args.artifact_dir, args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run audit tests**

Run:

```powershell
pytest tests/test_kg_artifact_audit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add pipeline/05_graph/audit_graph_artifacts.py tests/test_kg_artifact_audit.py
git commit -m "feat: add KG artifact audit"
```

## Task 4: Retrieval Service Core

**Files:**
- Create: `src/backend/services/retrieval_service.py`
- Create: `src/backend/services/rerank_service.py`
- Test: `tests/test_retrieval_service.py`

- [ ] **Step 1: Write failing retrieval service tests**

Create `tests/test_retrieval_service.py`:

```python
from contracts import RetrievalHit
from retrieval_modes import RetrievalRequest
from retrieval_service import FusionRetriever, RetrievalService


class FakeRetriever:
    def __init__(self, name, hits):
        self.name = name
        self.hits = hits
        self.calls = []

    def search(self, request, candidate_k):
        self.calls.append((request, candidate_k))
        return self.hits


class FakeReranker:
    def rerank(self, query, hits, top_k):
        for index, hit in enumerate(reversed(hits), start=1):
            hit.rank = index
            hit.scores["rerank"] = float(100 - index)
        return list(reversed(hits))[:top_k]


def make_hit(rank, chunk_id, score_key, score):
    return RetrievalHit(
        rank=rank,
        chunk_id=chunk_id,
        doc_id=chunk_id.split(":")[1],
        title=f"Doc {chunk_id}",
        document_number="01/2026/QH",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 1",
        text=f"Text {chunk_id}",
        scores={score_key: score},
        citation=f"Citation {chunk_id}",
    )


def test_fusion_retriever_merges_dense_sparse_by_rrf():
    dense = [make_hit(1, "chunk:1:000001", "dense", 0.9)]
    sparse = [make_hit(1, "chunk:2:000001", "sparse", 12.0)]
    fusion = FusionRetriever(k=60)

    merged = fusion.merge(dense, sparse, top_k=2)

    assert [hit.chunk_id for hit in merged] == ["chunk:1:000001", "chunk:2:000001"]
    assert all("rrf" in hit.scores for hit in merged)


def test_retrieval_service_resolves_hybrid_rerank():
    dense = FakeRetriever("dense", [make_hit(1, "chunk:1:000001", "dense", 0.9)])
    sparse = FakeRetriever("sparse", [make_hit(1, "chunk:2:000001", "sparse", 12.0)])
    service = RetrievalService(
        dense_retriever=dense,
        sparse_retriever=sparse,
        fusion_retriever=FusionRetriever(),
        reranker=FakeReranker(),
    )

    hits = service.search(
        RetrievalRequest(
            query="q",
            retrieval_mode="hybrid",
            rerank={"enabled": True, "candidate_k": 20},
            top_k=1,
        )
    )

    assert len(hits) == 1
    assert hits[0].scores["rerank"] > 0
    assert dense.calls[0][1] == 20
    assert sparse.calls[0][1] == 20
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_retrieval_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval_service'`.

- [ ] **Step 3: Implement deterministic reranker**

Create `src/backend/services/rerank_service.py`:

```python
from __future__ import annotations

from typing import Protocol

from contracts import RetrievalHit


class Reranker(Protocol):
    def rerank(self, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        ...


class NoopReranker:
    def rerank(self, query: str, hits: list[RetrievalHit], top_k: int) -> list[RetrievalHit]:
        return hits[:top_k]
```

- [ ] **Step 4: Implement RetrievalService and FusionRetriever**

Create `src/backend/services/retrieval_service.py`:

```python
from __future__ import annotations

from typing import Protocol

from contracts import RetrievalHit
from rerank_service import NoopReranker, Reranker
from retrieval_modes import RetrievalRequest


class Retriever(Protocol):
    def search(self, request: RetrievalRequest, candidate_k: int) -> list[RetrievalHit]:
        ...


class FusionRetriever:
    def __init__(self, k: int = 60) -> None:
        self.k = k

    def merge(
        self,
        dense_hits: list[RetrievalHit],
        sparse_hits: list[RetrievalHit],
        top_k: int,
    ) -> list[RetrievalHit]:
        by_chunk: dict[str, RetrievalHit] = {}
        rrf_scores: dict[str, float] = {}

        for source_hits in (dense_hits, sparse_hits):
            for rank, hit in enumerate(source_hits, start=1):
                if hit.chunk_id not in by_chunk:
                    by_chunk[hit.chunk_id] = hit
                else:
                    by_chunk[hit.chunk_id].scores.update(hit.scores)
                rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + 1.0 / (self.k + rank)

        merged = list(by_chunk.values())
        for hit in merged:
            hit.scores["rrf"] = rrf_scores[hit.chunk_id]

        merged.sort(key=lambda item: item.scores["rrf"], reverse=True)
        for rank, hit in enumerate(merged, start=1):
            hit.rank = rank
        return merged[:top_k]


class RetrievalService:
    def __init__(
        self,
        dense_retriever: Retriever,
        sparse_retriever: Retriever,
        fusion_retriever: FusionRetriever | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.fusion_retriever = fusion_retriever or FusionRetriever()
        self.reranker = reranker or NoopReranker()

    def search(self, request: RetrievalRequest) -> list[RetrievalHit]:
        candidate_k = request.rerank.candidate_k if request.rerank.enabled else request.top_k
        if request.retrieval_mode == "dense":
            hits = self.dense_retriever.search(request, candidate_k)
        elif request.retrieval_mode == "sparse":
            hits = self.sparse_retriever.search(request, candidate_k)
        else:
            dense_hits = self.dense_retriever.search(request, candidate_k)
            sparse_hits = self.sparse_retriever.search(request, candidate_k)
            hits = self.fusion_retriever.merge(dense_hits, sparse_hits, candidate_k)

        if request.rerank.enabled:
            return self.reranker.rerank(request.query, hits, request.top_k)
        return hits[:request.top_k]
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
pytest tests/test_retrieval_service.py tests/test_retrieval_modes.py -v
```

Expected: PASS.

Commit:

```powershell
git add src/backend/services/retrieval_service.py src/backend/services/rerank_service.py tests/test_retrieval_service.py
git commit -m "feat: add retrieval service core"
```

## Task 5: Intent Detector and Context Assembler

**Files:**
- Create: `src/backend/services/intent_detector.py`
- Create: `src/backend/services/context_assembler.py`
- Test: `tests/test_context_assembly.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_context_assembly.py`:

```python
from context_assembler import ContextAssembler
from contracts import AnswerContext, GraphContext, RetrievalHit
from intent_detector import IntentDetector


def test_intent_detector_finds_document_number_and_relation_intent():
    detected = IntentDetector().detect("Van ban 50/2014/QH13 bi sua doi boi van ban nao?")

    assert detected["document_number"] == "50/2014/QH13"
    assert detected["intent"] == "amendment"


def test_context_assembler_deduplicates_retrieval_and_graph_chunks():
    retrieval_hit = RetrievalHit(
        rank=1,
        chunk_id="chunk:1:000001",
        doc_id="1",
        title="Doc 1",
        document_number="01/2026/QH",
        legal_type="Luat",
        effect_status="Con hieu luc",
        section_path="Dieu 1",
        text="Retrieval text",
        scores={},
        citation="Doc 1, Dieu 1",
    )
    graph = GraphContext(
        center=None,
        related_chunks=[
            AnswerContext(
                source="graph",
                chunk_id="chunk:1:000001",
                doc_id="1",
                title="Doc 1",
                text="Graph duplicate",
                citation="Doc 1",
            ),
            AnswerContext(
                source="graph",
                chunk_id="chunk:2:000001",
                doc_id="2",
                title="Doc 2",
                text="Graph new",
                citation="Doc 2",
                relation="AMENDS",
                raw_label="Van ban sua doi",
            ),
        ],
        query_intent="amendment",
    )

    contexts = ContextAssembler().merge([retrieval_hit], graph)

    assert [item.chunk_id for item in contexts] == ["chunk:1:000001", "chunk:2:000001"]
    assert contexts[0].source == "retrieval"
    assert contexts[1].relation == "AMENDS"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_context_assembly.py -v
```

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement intent detector**

Create `src/backend/services/intent_detector.py`:

```python
from __future__ import annotations

import re


class IntentDetector:
    DOCUMENT_NUMBER_PATTERN = re.compile(r"\b\d{1,4}/\d{4}/[A-Z0-9-]+\b", re.IGNORECASE)

    def detect(self, query: str) -> dict[str, str | None]:
        normalized = query.lower()
        document_match = self.DOCUMENT_NUMBER_PATTERN.search(query)
        intent = "general"
        if any(term in normalized for term in ("sua doi", "bo sung", "sửa đổi", "bổ sung")):
            intent = "amendment"
        elif any(term in normalized for term in ("bai bo", "het hieu luc", "bãi bỏ", "hết hiệu lực")):
            intent = "repeal"
        elif any(term in normalized for term in ("dan chieu", "can cu", "dẫn chiếu", "căn cứ")):
            intent = "citation"
        elif any(term in normalized for term in ("huong dan", "quy dinh chi tiet", "hướng dẫn", "quy định chi tiết")):
            intent = "guideline"

        return {
            "intent": intent,
            "document_number": document_match.group(0) if document_match else None,
        }
```

- [ ] **Step 4: Implement context assembler**

Create `src/backend/services/context_assembler.py`:

```python
from __future__ import annotations

from contracts import AnswerContext, GraphContext, RetrievalHit


class ContextAssembler:
    def merge(
        self,
        retrieval_hits: list[RetrievalHit],
        graph_context: GraphContext | None,
    ) -> list[AnswerContext]:
        contexts: list[AnswerContext] = []
        seen_chunk_ids: set[str] = set()

        for hit in retrieval_hits:
            context = hit.to_answer_context()
            if context.chunk_id:
                seen_chunk_ids.add(context.chunk_id)
            contexts.append(context)

        if graph_context is None:
            return contexts

        for item in graph_context.related_chunks:
            if item.chunk_id and item.chunk_id in seen_chunk_ids:
                continue
            if item.chunk_id:
                seen_chunk_ids.add(item.chunk_id)
            contexts.append(item)

        return contexts
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
pytest tests/test_context_assembly.py -v
```

Expected: PASS.

Commit:

```powershell
git add src/backend/services/intent_detector.py src/backend/services/context_assembler.py tests/test_context_assembly.py
git commit -m "feat: add intent detection and context assembly"
```

## Task 6: GraphRetriever

**Files:**
- Create: `src/backend/services/graph_retriever.py`
- Test: `tests/test_graph_retriever.py`

- [ ] **Step 1: Write failing tests with fake Neo4j records**

Create `tests/test_graph_retriever.py`:

```python
from graph_retriever import GraphRetriever
from retrieval_modes import RetrievalRequest


class FakeRecord(dict):
    def data(self):
        return dict(self)


class FakeSession:
    def __init__(self):
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        if "RETURN d" in query:
            return [FakeRecord({"d": {"id": "doc:1", "doc_id": "1", "title": "Doc 1"}})]
        if "RETURN source" in query:
            return [
                FakeRecord(
                    {
                        "source": {"id": "doc:2", "doc_id": "2", "title": "Doc 2"},
                        "target": {"id": "doc:1", "doc_id": "1", "title": "Doc 1"},
                        "type": "AMENDS",
                        "raw_label": "Van ban sua doi",
                    }
                )
            ]
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeDriver:
    def __init__(self):
        self.session_obj = FakeSession()

    def session(self, database=None):
        return self.session_obj


def test_graph_retriever_returns_neighbors_with_raw_label():
    retriever = GraphRetriever(driver=FakeDriver(), database="neo4j")

    context = retriever.get_document_neighbors("1", relations=["AMENDS"], depth=1)

    payload = context.to_dict()
    assert payload["center"]["properties"]["doc_id"] == "1"
    assert payload["edges"][0]["type"] == "AMENDS"
    assert payload["edges"][0]["raw_label"] == "Van ban sua doi"


def test_graph_retriever_protocol_retrieve_uses_retrieval_hit_doc_id():
    retriever = GraphRetriever(driver=FakeDriver(), database="neo4j")

    context = retriever.retrieve(
        query="Van ban nao sua doi?",
        retrieval_hits=[{"doc_id": "1"}],
        max_hops=1,
    )

    assert context.query_intent == "amendment"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_graph_retriever.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'graph_retriever'`.

- [ ] **Step 3: Implement GraphRetriever**

Create `src/backend/services/graph_retriever.py`:

```python
from __future__ import annotations

from typing import Any

from contracts import GraphContext, GraphEdge, GraphNode
from intent_detector import IntentDetector


class GraphRetriever:
    def __init__(self, driver: Any, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database
        self.intent_detector = IntentDetector()

    def get_document_neighbors(
        self,
        doc_id: str,
        relations: list[str] | None = None,
        depth: int = 1,
    ) -> GraphContext:
        relation_filter = relations or ["AMENDS", "CITES", "REPEALS", "GUIDELINES"]
        with self.driver.session(database=self.database) as session:
            center_records = list(
                session.run(
                    "MATCH (d:Document) WHERE d.doc_id = $doc_id OR d.id = $node_id RETURN d",
                    doc_id=doc_id,
                    node_id=f"doc:{doc_id}",
                )
            )
            center = self._node_from_record(center_records[0]["d"]) if center_records else None
            edge_records = list(
                session.run(
                    """
                    MATCH (source:Document)-[rel]-(target:Document)
                    WHERE (source.doc_id = $doc_id OR source.id = $node_id OR target.doc_id = $doc_id OR target.id = $node_id)
                      AND type(rel) IN $relations
                    RETURN source, target, type(rel) AS type, rel.raw_label AS raw_label
                    LIMIT 100
                    """,
                    doc_id=doc_id,
                    node_id=f"doc:{doc_id}",
                    relations=relation_filter,
                    depth=depth,
                )
            )

        nodes_by_id: dict[str, GraphNode] = {}
        if center:
            nodes_by_id[center.id] = center
        edges: list[GraphEdge] = []
        center_id = center.id if center else f"doc:{doc_id}"
        for record in edge_records:
            source = self._node_from_record(record["source"])
            target = self._node_from_record(record["target"])
            nodes_by_id[source.id] = source
            nodes_by_id[target.id] = target
            direction = "out" if source.id == center_id else "in"
            edges.append(
                GraphEdge(
                    source=source.id,
                    target=target.id,
                    type=record["type"],
                    raw_label=record.get("raw_label") or "",
                    direction=direction,
                )
            )

        return GraphContext(
            center=center,
            nodes=list(nodes_by_id.values()),
            edges=edges,
            related_chunks=[],
            query_intent="general",
        )

    def retrieve(
        self,
        query: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext:
        detected = self.intent_detector.detect(query)
        doc_id = self._doc_id_from_hits(retrieval_hits)
        if not doc_id:
            return GraphContext(center=None, query_intent=detected["intent"] or "general")
        context = self.get_document_neighbors(doc_id, depth=max_hops)
        context.query_intent = detected["intent"] or "general"
        return context

    def _doc_id_from_hits(self, retrieval_hits: list[dict[str, Any]]) -> str | None:
        for hit in retrieval_hits:
            doc_id = hit.get("doc_id")
            if doc_id:
                return str(doc_id)
        return None

    def _node_from_record(self, value: Any) -> GraphNode:
        properties = dict(value)
        node_id = str(properties.get("id") or f"doc:{properties.get('doc_id', '')}")
        return GraphNode(id=node_id, label="Document", properties=properties)
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest tests/test_graph_retriever.py tests/test_context_assembly.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/backend/services/graph_retriever.py tests/test_graph_retriever.py
git commit -m "feat: add Neo4j graph retriever"
```

## Task 7: AnswerService and LightRAG Update

**Files:**
- Create: `src/backend/services/answer_service.py`
- Modify: `src/backend/services/lightrag_service.py`
- Test: `tests/test_lightrag_service.py`
- Test: `tests/test_answer_service.py`

- [ ] **Step 1: Add answer service tests**

Create `tests/test_answer_service.py`:

```python
from answer_service import ExtractiveAnswerService
from contracts import AnswerContext


def test_extractive_answer_service_returns_answer_and_citations():
    service = ExtractiveAnswerService()

    result = service.answer(
        query="q",
        contexts=[
            AnswerContext(
                source="retrieval",
                chunk_id="chunk:1:000001",
                doc_id="1",
                title="Doc 1",
                text="Noi dung tra loi",
                citation="Doc 1, Dieu 1",
            )
        ],
        temperature=0.2,
    )

    assert "Noi dung tra loi" in result["answer"]
    assert result["citations"][0]["chunk_id"] == "chunk:1:000001"
```

- [ ] **Step 2: Update LightRAG tests for contract output**

Modify `tests/test_lightrag_service.py` so fake services use `RetrievalHit`, `GraphContext` and `AnswerContext`:

```python
from contracts import AnswerContext, GraphContext, RetrievalHit
from lightrag_service import LightRAGService
from retrieval_modes import RetrievalRequest


class FakeRetrievalService:
    def search(self, request):
        return [
            RetrievalHit(
                rank=1,
                chunk_id="chunk:1:000001",
                doc_id="1",
                title="Doc 1",
                document_number="01/2026/QH",
                legal_type="Luat",
                effect_status="Con hieu luc",
                section_path="Dieu 1",
                text="retrieved text",
                scores={},
                citation="Doc 1, Dieu 1",
            )
        ]


class FakeGraphRetriever:
    def __init__(self, fail=False):
        self.fail = fail

    def retrieve(self, query, retrieval_hits, max_hops):
        if self.fail:
            raise RuntimeError("neo4j unavailable")
        return GraphContext(
            center=None,
            related_chunks=[
                AnswerContext(
                    source="graph",
                    chunk_id="chunk:2:000001",
                    doc_id="2",
                    title="Doc 2",
                    text="graph text",
                    citation="Doc 2",
                    relation="CITES",
                    raw_label="Van ban can cu",
                )
            ],
            query_intent="citation",
        )


class FakeAnswerService:
    def __init__(self):
        self.calls = []

    def answer(self, query, contexts, temperature):
        self.calls.append((query, contexts, temperature))
        return {"answer": "answer text", "citations": [{"chunk_id": contexts[0].chunk_id}]}


def test_lightrag_service_merges_retrieval_graph_and_answer_contexts():
    answer = FakeAnswerService()
    service = LightRAGService(FakeRetrievalService(), FakeGraphRetriever(), answer)

    result = service.answer(
        RetrievalRequest(
            query="Van ban nao dan chieu den quy dinh nay?",
            llm={"temperature": 0.4},
            graph={"enabled": True, "use_lightrag": True, "max_hops": 2},
        )
    )

    assert result["answer"] == "answer text"
    assert result["retrieval_trace"]["execution_mode"] == "hybrid_rerank"
    assert result["retrieval_trace"]["lightrag_enabled"] is True
    assert len(answer.calls[0][1]) == 2
    assert answer.calls[0][2] == 0.4


def test_lightrag_service_falls_back_when_graph_retrieval_fails():
    service = LightRAGService(
        FakeRetrievalService(),
        FakeGraphRetriever(fail=True),
        FakeAnswerService(),
    )

    result = service.answer(RetrievalRequest(query="q"))

    assert result["graph_context"] == {}
    assert result["retrieval_trace"]["lightrag_enabled"] is False
    assert "neo4j unavailable" in result["retrieval_trace"]["lightrag_error"]
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```powershell
pytest tests/test_answer_service.py tests/test_lightrag_service.py -v
```

Expected: FAIL until `answer_service.py` and updated LightRAG contract handling exist.

- [ ] **Step 4: Implement AnswerService**

Create `src/backend/services/answer_service.py`:

```python
from __future__ import annotations

from typing import Any, Protocol

from contracts import AnswerContext


class AnswerService(Protocol):
    def answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> dict[str, Any]:
        ...


class ExtractiveAnswerService:
    def answer(
        self,
        query: str,
        contexts: list[AnswerContext],
        temperature: float,
    ) -> dict[str, Any]:
        if not contexts:
            return {
                "answer": "Không tìm thấy đủ ngữ cảnh để trả lời.",
                "citations": [],
            }
        answer_text = "\n\n".join(context.text for context in contexts[:3] if context.text)
        citations = [
            {
                "chunk_id": context.chunk_id,
                "doc_id": context.doc_id,
                "title": context.title,
                "citation": context.citation,
            }
            for context in contexts
        ]
        return {"answer": answer_text, "citations": citations}
```

- [ ] **Step 5: Update LightRAGService**

Modify `src/backend/services/lightrag_service.py` to:

```python
from __future__ import annotations

from typing import Any, Protocol

from context_assembler import ContextAssembler
from contracts import GraphContext, RetrievalHit
from retrieval_modes import RetrievalRequest


class RetrievalService(Protocol):
    def search(self, request: RetrievalRequest) -> list[RetrievalHit]:
        ...


class GraphRetriever(Protocol):
    def retrieve(
        self,
        query: str,
        retrieval_hits: list[dict[str, Any]],
        max_hops: int,
    ) -> GraphContext | dict[str, Any]:
        ...


class AnswerService(Protocol):
    def answer(self, query: str, contexts: list[Any], temperature: float) -> dict[str, Any]:
        ...


class LightRAGService:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        graph_retriever: GraphRetriever,
        answer_service: AnswerService,
        context_assembler: ContextAssembler | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.graph_retriever = graph_retriever
        self.answer_service = answer_service
        self.context_assembler = context_assembler or ContextAssembler()

    def answer(self, request: RetrievalRequest) -> dict[str, Any]:
        retrieval_hits = self.retrieval_service.search(request)
        graph_context: GraphContext | None = None
        graph_payload: dict[str, Any] = {}
        lightrag_enabled = bool(request.graph.enabled and request.graph.use_lightrag)
        lightrag_error = None

        if lightrag_enabled:
            try:
                raw_graph_context = self.graph_retriever.retrieve(
                    request.query,
                    [hit.to_dict() for hit in retrieval_hits],
                    request.graph.max_hops,
                )
                if isinstance(raw_graph_context, GraphContext):
                    graph_context = raw_graph_context
                    graph_payload = graph_context.to_dict()
                else:
                    graph_payload = raw_graph_context
            except Exception as exc:
                lightrag_enabled = False
                lightrag_error = str(exc)

        contexts = self.context_assembler.merge(retrieval_hits, graph_context)
        answer_payload = self.answer_service.answer(
            request.query,
            contexts,
            request.llm.temperature,
        )

        trace = {
            "retrieval_mode": request.retrieval_mode,
            "execution_mode": request.execution_mode,
            "reranked": request.rerank.enabled,
            "temperature": request.llm.temperature,
            "graph_enabled": request.graph.enabled,
            "lightrag_enabled": lightrag_enabled,
            "retrieval_hits": len(retrieval_hits),
            "graph_hits": len(graph_context.related_chunks) if graph_context else 0,
        }
        if lightrag_error:
            trace["lightrag_error"] = lightrag_error

        return {
            "answer": answer_payload.get("answer", ""),
            "citations": answer_payload.get("citations", []),
            "retrieval_context": [hit.to_dict() for hit in retrieval_hits],
            "graph_context": graph_payload,
            "retrieval_trace": trace,
        }
```

Run:

```powershell
pytest tests/test_answer_service.py tests/test_lightrag_service.py -v
```

Expected: PASS.

Commit:

```powershell
git add src/backend/services/answer_service.py src/backend/services/lightrag_service.py tests/test_answer_service.py tests/test_lightrag_service.py
git commit -m "feat: update LightRAG orchestration"
```

## Task 8: FastAPI App and Schemas

**Files:**
- Create: `src/backend/app/config.py`
- Create: `src/backend/app/schemas.py`
- Create: `src/backend/app/dependencies.py`
- Create: `src/backend/app/main.py`
- Create: `src/backend/app/routes/health.py`
- Create: `src/backend/app/routes/search.py`
- Create: `src/backend/app/routes/documents.py`
- Modify: `pyproject.toml`
- Test: `tests/test_api_contract.py`

- [ ] **Step 1: Write API contract tests**

Create `tests/test_api_contract.py`:

```python
from fastapi.testclient import TestClient

from main import create_app


def test_health_endpoint_reports_configured_services():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert "elasticsearch" in payload
    assert "neo4j" in payload


def test_search_endpoint_accepts_mvp_request():
    client = TestClient(create_app())

    response = client.post(
        "/search",
        json={
            "query": "Dieu kien cap giay phep xay dung la gi?",
            "retrieval_mode": "hybrid",
            "rerank": {"enabled": False},
            "top_k": 2,
            "filters": {"effect_status": "Con hieu luc"},
            "graph": {"enabled": False, "use_lightrag": False, "max_hops": 1},
            "llm": {"temperature": 0.2, "max_context_chunks": 8},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["execution_mode"] == "hybrid"
    assert "results" in payload


def test_answer_endpoint_returns_trace():
    client = TestClient(create_app())

    response = client.post(
        "/answer",
        json={
            "query": "Van ban nao sua doi quy dinh nay?",
            "retrieval_mode": "hybrid",
            "rerank": {"enabled": True, "candidate_k": 5},
            "top_k": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert payload["retrieval_trace"]["execution_mode"] == "hybrid_rerank"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_api_contract.py -v
```

Expected: FAIL with missing `main` module or app package.

- [ ] **Step 3: Implement config and schemas**

Create `src/backend/app/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    elasticsearch_url: str = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")


def get_settings() -> Settings:
    return Settings()
```

Create `src/backend/app/schemas.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RerankConfigModel(BaseModel):
    enabled: bool = True
    model: str = "BAAI/bge-reranker-v2-m3"
    candidate_k: int = Field(default=50, gt=0)
    batch_size: int = Field(default=8, gt=0)
    device: str = "auto"
    timeout_ms: int = Field(default=30000, gt=0)


class LLMConfigModel(BaseModel):
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    max_context_chunks: int = Field(default=8, gt=0)


class GraphConfigModel(BaseModel):
    enabled: bool = True
    use_lightrag: bool = True
    max_hops: int = Field(default=1, ge=0)


class SearchRequestModel(BaseModel):
    query: str
    retrieval_mode: Literal["dense", "sparse", "hybrid"] = "hybrid"
    rerank: RerankConfigModel = Field(default_factory=RerankConfigModel)
    top_k: int = Field(default=5, gt=0)
    filters: dict[str, Any] = Field(default_factory=dict)
    graph: GraphConfigModel = Field(default_factory=GraphConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    include_trace: bool = True
```

- [ ] **Step 4: Implement app with deterministic demo dependencies**

Modify `pyproject.toml` so pytest can import the app package:

```toml
[tool.pytest.ini_options]
pythonpath = [
    ".",
    "pipeline/03_preprocessing/chunk",
    "pipeline/04_embedding",
    "pipeline/05_graph",
    "pipeline/07_evaluation",
    "src/backend/services",
    "src/backend/app"
]
```

Create `src/backend/app/dependencies.py`:

```python
from __future__ import annotations

from contracts import RetrievalHit
from retrieval_modes import RetrievalRequest


class DemoRetrievalService:
    def search(self, request: RetrievalRequest) -> list[RetrievalHit]:
        return [
            RetrievalHit(
                rank=1,
                chunk_id="chunk:demo:000001",
                doc_id="demo",
                title="Van ban demo",
                document_number="01/2026/QH",
                legal_type="Luat",
                effect_status="Con hieu luc",
                section_path="Dieu 1",
                text="Noi dung demo cho cau hoi.",
                scores={"rrf": 0.03},
                citation="Van ban demo, Dieu 1",
            )
        ][: request.top_k]
```

Create `src/backend/app/main.py`:

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from routes.documents import router as documents_router
from routes.health import router as health_router
from routes.search import router as search_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="VietLegalGraphRAG API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin, "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(search_router)
    app.include_router(documents_router)
    return app


app = create_app()
```

Create route files:

```python
# src/backend/app/routes/health.py
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "degraded",
        "elasticsearch": "not_checked",
        "neo4j": "not_checked",
        "llm": "mock",
    }
```

```python
# src/backend/app/routes/search.py
from __future__ import annotations

from fastapi import APIRouter

from dependencies import DemoRetrievalService
from retrieval_modes import RetrievalRequest
from schemas import SearchRequestModel

router = APIRouter()


@router.post("/search")
def search(request: SearchRequestModel) -> dict:
    retrieval_request = RetrievalRequest(**request.model_dump())
    hits = DemoRetrievalService().search(retrieval_request)
    return {
        "query": retrieval_request.query,
        "retrieval_mode": retrieval_request.retrieval_mode,
        "execution_mode": retrieval_request.execution_mode,
        "latency_ms": 0,
        "results": [hit.to_dict() for hit in hits],
        "warnings": ["demo_dependency"],
    }


@router.post("/answer")
def answer(request: SearchRequestModel) -> dict:
    retrieval_request = RetrievalRequest(**request.model_dump())
    hits = DemoRetrievalService().search(retrieval_request)
    return {
        "answer": hits[0].text if hits else "Không tìm thấy đủ ngữ cảnh để trả lời.",
        "citations": [{"chunk_id": hit.chunk_id, "doc_id": hit.doc_id, "title": hit.title} for hit in hits],
        "retrieval_context": [hit.to_dict() for hit in hits],
        "graph_context": {},
        "retrieval_trace": {
            "retrieval_mode": retrieval_request.retrieval_mode,
            "execution_mode": retrieval_request.execution_mode,
            "reranked": retrieval_request.rerank.enabled,
            "temperature": retrieval_request.llm.temperature,
            "graph_enabled": retrieval_request.graph.enabled,
            "lightrag_enabled": False,
        },
        "latency_ms": 0,
    }
```

```python
# src/backend/app/routes/documents.py
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/documents/{doc_id}/graph")
def document_graph(doc_id: str) -> dict:
    return {
        "center": {"id": f"doc:{doc_id}", "label": "Document", "properties": {"doc_id": doc_id}},
        "nodes": [],
        "edges": [],
        "related_chunks": [],
        "query_intent": "general",
    }


@router.get("/documents/{doc_id}/version-chain")
def version_chain(doc_id: str) -> dict:
    return {"doc_id": doc_id, "chain": []}
```

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
pytest tests/test_api_contract.py -v
```

Expected: PASS.

Commit:

```powershell
git add pyproject.toml src/backend/app tests/test_api_contract.py
git commit -m "feat: add FastAPI MVP contract"
```

## Task 9: Frontend API Contract and Mocks

**Files:**
- Create: `src/frontend/API_CONTRACT.md`
- Create: `src/frontend/mocks/search_response.json`
- Create: `src/frontend/mocks/answer_response.json`

- [ ] **Step 1: Create frontend contract**

Create `src/frontend/API_CONTRACT.md`:

```markdown
# Frontend API Contract

Frontend calls the FastAPI backend only. It does not call Elasticsearch, Neo4j, reranker models or LLM providers directly.

## Controls

- `retrieval_mode`: `dense`, `sparse`, `hybrid`.
- `rerank.enabled`: boolean.
- `rerank.candidate_k`: integer, must be greater than or equal to `top_k`.
- `llm.temperature`: number from `0.0` to `1.0`, default `0.2`.
- `graph.enabled`: boolean.
- `graph.use_lightrag`: boolean.
- `graph.max_hops`: integer from `0` upward.

## POST /search

Returns retrieval results without generating an LLM answer.

## POST /answer

Returns answer, citations, retrieval context, graph context and trace.

## GET /documents/{doc_id}/graph

Returns center document, graph nodes, graph edges and related chunks.

## GET /documents/{doc_id}/version-chain

Returns legal update chain for one document.
```

- [ ] **Step 2: Create search mock**

Create `src/frontend/mocks/search_response.json`:

```json
{
  "query": "Dieu kien cap giay phep xay dung la gi?",
  "retrieval_mode": "hybrid",
  "execution_mode": "hybrid_rerank",
  "latency_ms": 420,
  "results": [
    {
      "rank": 1,
      "chunk_id": "chunk:demo:000001",
      "doc_id": "demo",
      "title": "Van ban demo",
      "document_number": "01/2026/QH",
      "legal_type": "Luat",
      "effect_status": "Con hieu luc",
      "section_path": "Dieu 1",
      "text": "Noi dung demo.",
      "scores": {
        "rrf": 0.03,
        "rerank": 0.8
      },
      "citation": "Van ban demo, Dieu 1"
    }
  ],
  "warnings": []
}
```

- [ ] **Step 3: Create answer mock**

Create `src/frontend/mocks/answer_response.json`:

```json
{
  "answer": "Noi dung tra loi demo.",
  "citations": [
    {
      "chunk_id": "chunk:demo:000001",
      "doc_id": "demo",
      "title": "Van ban demo"
    }
  ],
  "retrieval_context": [],
  "graph_context": {
    "center": null,
    "nodes": [],
    "edges": [],
    "related_chunks": [],
    "query_intent": "general"
  },
  "retrieval_trace": {
    "retrieval_mode": "hybrid",
    "execution_mode": "hybrid_rerank",
    "reranked": true,
    "temperature": 0.2,
    "graph_enabled": true,
    "lightrag_enabled": true
  },
  "latency_ms": 1200
}
```

- [ ] **Step 4: Validate JSON**

Run:

```powershell
python -m json.tool src/frontend/mocks/search_response.json | Out-Null
python -m json.tool src/frontend/mocks/answer_response.json | Out-Null
```

Expected: no output.

- [ ] **Step 5: Commit**

```powershell
git add src/frontend/API_CONTRACT.md src/frontend/mocks/search_response.json src/frontend/mocks/answer_response.json
git commit -m "docs: add frontend API contract"
```

## Task 10: Docker Compose Demo Skeleton

**Files:**
- Create: `src/backend/Dockerfile`
- Create: `src/infra/.env.example`
- Create: `src/infra/docker-compose.yml`
- Modify: `src/infra/README.md`

- [ ] **Step 1: Create backend Dockerfile**

Create `src/backend/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY src/backend /app/src/backend

ENV PYTHONPATH=/app/src/backend/services:/app/src/backend/app
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/src/backend/app"]
```

- [ ] **Step 2: Create infra env**

Create `src/infra/.env.example`:

```dotenv
ELASTIC_PASSWORD=changeme
NEO4J_AUTH=neo4j/password
BACKEND_PORT=8000
```

- [ ] **Step 3: Create compose file**

Create `src/infra/docker-compose.yml`:

```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.13.4
    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"
      ES_JAVA_OPTS: "-Xms1g -Xmx1g"
    ports:
      - "9200:9200"
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://localhost:9200/_cluster/health || exit 1"]
      interval: 20s
      timeout: 5s
      retries: 10

  neo4j:
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: ${NEO4J_AUTH:-neo4j/password}
      NEO4J_PLUGINS: '["apoc"]'
    ports:
      - "7474:7474"
      - "7687:7687"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 || exit 1"]
      interval: 20s
      timeout: 5s
      retries: 10

  api:
    build:
      context: ../..
      dockerfile: src/backend/Dockerfile
    environment:
      ELASTICSEARCH_URL: http://elasticsearch:9200
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: password
      LLM_PROVIDER: mock
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    depends_on:
      elasticsearch:
        condition: service_healthy
      neo4j:
        condition: service_healthy
```

- [ ] **Step 4: Update infra README**

Add:

````markdown
## Local Demo

```powershell
Copy-Item src/infra/.env.example src/infra/.env
docker compose --env-file src/infra/.env -f src/infra/docker-compose.yml up --build
```

API health check:

```powershell
Invoke-RestMethod http://localhost:8000/health
```
````

- [ ] **Step 5: Validate compose config and commit**

Run:

```powershell
docker compose -f src/infra/docker-compose.yml config
```

Expected: compose config renders successfully.

Commit:

```powershell
git add src/backend/Dockerfile src/infra/.env.example src/infra/docker-compose.yml src/infra/README.md
git commit -m "chore: add demo docker compose stack"
```

## Task 11: Neo4j Verification Script

**Files:**
- Create: `pipeline/05_graph/verify_neo4j.py`
- Test: `tests/test_neo4j_verification.py`

- [ ] **Step 1: Write verification formatter test**

Create `tests/test_neo4j_verification.py`:

```python
from verify_neo4j import format_import_report


def test_format_import_report_contains_counts_and_samples():
    report = format_import_report(
        counts={"Document": 2, "Chunk": 3, "AMENDS": 1},
        samples=[{"source": "doc:2", "target": "doc:1", "type": "AMENDS"}],
    )

    assert "Neo4j Import Report" in report
    assert "Document: 2" in report
    assert "doc:2" in report
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_neo4j_verification.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement verification script**

Create `pipeline/05_graph/verify_neo4j.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def format_import_report(counts: dict[str, int], samples: list[dict[str, Any]]) -> str:
    lines = ["# Neo4j Import Report", "", "## Counts"]
    for key, value in sorted(counts.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Samples"])
    for sample in samples:
        lines.append(f"- {sample}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a Neo4j import verification report shell.")
    parser.add_argument("--output", default="output/kg_quality/neo4j_import_report.md")
    args = parser.parse_args()
    report = format_import_report(counts={}, samples=[])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test**

Run:

```powershell
pytest tests/test_neo4j_verification.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add pipeline/05_graph/verify_neo4j.py tests/test_neo4j_verification.py
git commit -m "feat: add Neo4j verification report helper"
```

## Task 12: Graph Evaluation Hook

**Files:**
- Create: `pipeline/07_evaluation/evaluate_graph.py`
- Test: `tests/test_graph_evaluation.py`

- [ ] **Step 1: Write metric tests**

Create `tests/test_graph_evaluation.py`:

```python
from evaluate_graph import precision_recall


def test_precision_recall_handles_empty_predictions():
    metrics = precision_recall(predicted=set(), gold={"doc:1"})

    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0


def test_precision_recall_scores_overlap():
    metrics = precision_recall(predicted={"doc:1", "doc:2"}, gold={"doc:2", "doc:3"})

    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
pytest tests/test_graph_evaluation.py -v
```

Expected: FAIL with missing module.

- [ ] **Step 3: Implement metrics**

Create `pipeline/07_evaluation/evaluate_graph.py`:

```python
from __future__ import annotations


def precision_recall(predicted: set[str], gold: set[str]) -> dict[str, float]:
    if not predicted:
        precision = 0.0
    else:
        precision = len(predicted & gold) / len(predicted)
    if not gold:
        recall = 0.0
    else:
        recall = len(predicted & gold) / len(gold)
    return {"precision": precision, "recall": recall}
```

- [ ] **Step 4: Run test**

Run:

```powershell
pytest tests/test_graph_evaluation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add pipeline/07_evaluation/evaluate_graph.py tests/test_graph_evaluation.py
git commit -m "feat: add graph evaluation metrics"
```

## Task 13: Final Verification

**Files:**
- Modify only files required by failures found in this task.

- [ ] **Step 1: Run focused test suite**

Run:

```powershell
pytest tests/test_knowledge_graph.py tests/test_retrieval_modes.py tests/test_service_contracts.py tests/test_retrieval_service.py tests/test_context_assembly.py tests/test_graph_retriever.py tests/test_answer_service.py tests/test_lightrag_service.py tests/test_api_contract.py tests/test_kg_artifact_audit.py tests/test_neo4j_verification.py tests/test_graph_evaluation.py -v
```

Expected: PASS.

- [ ] **Step 2: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output.

- [ ] **Step 3: Run docs JSON validation**

Run:

```powershell
python -m json.tool src/frontend/mocks/search_response.json | Out-Null
python -m json.tool src/frontend/mocks/answer_response.json | Out-Null
```

Expected: no output.

- [ ] **Step 4: Inspect status**

Run:

```powershell
git status --short
```

Expected: only intentional files from the current task are modified or untracked.

- [ ] **Step 5: Finish verification**

If Step 1 to Step 4 required fixes, return to the task that owns the failing file, apply the fix there, rerun this final verification task, and use that task's commit command. If no fixes were needed, do not create an empty commit.
