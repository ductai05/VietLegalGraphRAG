# VietLegal GraphRAG — Developer Guide & LangChain Agent Integration Spec

This document gives developers a full picture of the current system architecture, how the Open WebUI frontend connects to the RAG core (`vietlegal_rag`), and a **complete, implementation-ready specification for adding a LangGraph ReAct Agent**.

Sections 1–3 describe what exists today. Sections 4–8 are the specification to implement. Section 9 lists the decisions already made (do not re-ask them) and the remaining open questions.

---

## 1. System Overview

VietLegal GraphRAG runs as cooperating Docker containers:

```mermaid
graph TD
    User([User]) -->|Chat UI| OpenWebUI[Open WebUI Container]
    OpenWebUI -->|Internal API| SQL[SQLite webui.db]
    OpenWebUI -->|Import & Run| Pipe[Pipe Function: vietlegal_rag.pipe]

    subgraph RAG Core Package (vietlegal_rag)
        Pipe -->|Build dependency graph| Deps[dependencies.py]
        Deps -->|Service call| LightRAG[LightRAGService]
        LightRAG -->|Hybrid search| ES[Elasticsearch Retriever]
        LightRAG -->|Graph lookup| Neo4j[Graph Retriever]
        LightRAG -->|Answer generation| LLM[Answer Service]
    end

    ES -->|Cloud / Local| ES_DB[(Elasticsearch Cloud)]
    Neo4j -->|Graph Database| Neo4j_DB[(Neo4j Instance)]
    LLM -->|Chat API| Ext_LLM[LLM Server: Qwen / DeepSeek]
```

### Main components

1. **Open WebUI (frontend + web backend).** Chat UI for end users. SvelteKit frontend and FastAPI backend live under `src/open-webui/`.
2. **VietLegal RAG package (`vietlegal_rag`).** Custom Python package at `src/vietlegal_rag/`. Holds all domain logic: RAG orchestration, DB connectivity, answer generation.
3. **Databases.**
   - **Elasticsearch Cloud** — stores and searches legal chunks: dense vectors + BM25 keyword search.
   - **Neo4j** — legal knowledge graph (links between articles, replacing/amending/expired documents).

### 1.1 Import convention (IMPORTANT — do not break this)

The package uses a **flat import style backed by a `sys.path` hack**, because Open WebUI loads `pipe.py` as a standalone function file.

- `src/vietlegal_rag/__init__.py`, `dependencies.py`, and `pipe.py` all prepend `src/vietlegal_rag/` and `src/vietlegal_rag/services/` to `sys.path`.
- Therefore modules inside `services/` import each other **flat**, not by package path:

```python
# CORRECT — this is what every file in services/ does
from contracts import AnswerContext, GraphContext, RetrievalHit
from retrieval_modes import RetrievalRequest

# WRONG — do not do this inside services/
from vietlegal_rag.services.contracts import AnswerContext
```

New agent modules under `services/` **must follow the flat convention.**

---

## 2. Open WebUI ↔ RAG Core Integration

Connection happens through a **Pipe Function** (Open WebUI's extension mechanism).

### 2.1 `src/vietlegal_rag/pipe.py`

- Class `Pipe` defines a virtual model named **VietLegal RAG** in Open WebUI.
- Class `Pipe.Valves` (a `pydantic.BaseModel`) holds runtime config shown in the Admin Panel: Elasticsearch/Neo4j credentials, `top_k`, graph on/off, LLM settings, etc. Every `Valves` default is read from the container's environment (`os.environ.get(...)`).
- `Pipe.__init__` starts a background thread (`_prewarm_services`) that eagerly builds services so the heavy embedding model does not cause an SSE timeout on the first query.
- `async def pipe(self, body, __user__, __event_emitter__) -> AsyncGenerator[str, None]` is the entrypoint. It:
  1. calls `self._get_services()` (thread-safe lazy init → `vietlegal_rag.build_services(self.valves)`),
  2. builds a `RetrievalRequest`,
  3. calls `services.lightrag_service.stream_answer(request)`,
  4. yields answer tokens one by one,
  5. appends a `📚 Căn cứ pháp lý:` citations block,
  6. emits status updates via `__event_emitter__`.

### 2.2 `vietlegal_rag.build_services(valves)` (`__init__.py`)

Maps `Valves` attributes back onto `os.environ`, calls `get_settings.cache_clear()`, then returns `get_runtime_services()`.

> **Any new valve that must reach `Settings` has to be added to the `env_mappings` dict in `__init__.py` — otherwise it is silently ignored.**

### 2.3 Auto-registration: `src/infra/scripts/init_pipe.py`

On Open WebUI container start, this script:

- waits for Open WebUI's SQLite DB to become ready (`/ready`),
- logs in with the default admin account,
- uploads `pipe.py` source via `/api/v1/functions/create` or `/update`,
- writes SQLite directly to activate the model (`is_active = 1`, `is_global = 1`).

---

## 3. Current RAG Pipeline Flow

Static flow, implemented in `src/vietlegal_rag/services/lightrag_service.py`:

```
User Query ──> [Elasticsearch Retrieval] ──> retrieve chunks
           ──> [Neo4j Graph Retrieval]   ──> retrieve related entities / relations
           ──> [Context Assembler]       ──> merge context, resolve legal effect
                                             (warn on expired / superseded documents)
           ──> [Answer Service (LLM)]     ──> generate answer + legal basis
```

### 3.1 Key existing types (agent code must reuse these — do not redefine)

From `services/contracts.py`:

```python
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
    scores: dict[str, float]
    citation: str
    def to_dict(self) -> dict[str, Any]: ...
    def to_answer_context(self) -> AnswerContext: ...

@dataclass
class AnswerContext:
    source: Literal["retrieval", "graph"]
    chunk_id: str | None
    doc_id: str
    title: str
    text: str
    citation: str
    relation: str | None = None
    raw_label: str | None = None
    effect_status: str = ""
    resolution: dict[str, Any] | None = None

@dataclass
class GraphContext:
    center: GraphNode | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    related_chunks: list[AnswerContext]
    query_intent: str
```

From `services/retrieval_modes.py`:

```python
@dataclass
class RetrievalRequest:
    query: str
    retrieval_mode: Literal["dense","sparse","hybrid"] = "hybrid"
    rerank: RerankConfig  # enabled, provider, model, candidate_k, batch_size, device, timeout_ms
    top_k: int = 5        # 1..50
    filters: dict[str, Any]
    llm: LLMConfig        # temperature (0..1), max_context_chunks (1..32), max_tokens
    graph: GraphConfig    # enabled, use_lightrag, max_hops (0..2), auto_depth
    include_trace: bool = True
```

Existing service methods the agent tools will wrap:

```python
RetrievalService.search(request: RetrievalRequest) -> list[RetrievalHit]
GraphRetriever.retrieve(query: str, retrieval_hits: list[dict], max_hops: int, auto_depth: bool = True) -> GraphContext
GraphRetriever.get_document_neighbors(doc_id: str, relations: list[str] | None = None, depth: int = 1) -> GraphContext
GraphRetriever.get_version_chain(doc_id: str) -> list[dict]   # oldest→newest: {doc_id, title, document_number, status, version_order}
```

`NoopGraphRetriever` (in `dependencies.py`) implements the same surface returning empties — **agent tools must tolerate empty graph results**, that is the configured degradation path when Neo4j is absent.

> **Pre-existing bug to fix as step 0 (§6).** `NoopGraphRetriever.retrieve` is declared without the `auto_depth` parameter, but `LightRAGService.answer`/`.stream_answer` both call `self.graph_retriever.retrieve(..., auto_depth=request.graph.auto_depth)`. With Neo4j down this raises `TypeError`, swallowed by the surrounding `except` and reported as `lightrag_error = "graph.retrieval_failed"` — a misleading trace for a signature mismatch. Add `auto_depth: bool = True` to `NoopGraphRetriever.retrieve` **and** to the `GraphRetriever` `Protocol` in `lightrag_service.py` (which is also missing it).

### 3.2 Citation string format (agent code must parse, not re-invent)

`services/elasticsearch_retriever.py::format_citation` packs four fields pipe-delimited, skipping empties:

```python
parts = [document_number, title, section_path, f"chunk_id: {chunk_id}"]
return " | ".join(part for part in parts if part)
# "15/2020/NĐ-CP | Nghị định 15/2020/NĐ-CP quy định xử phạt... | Điều 101 | chunk_id: chunk:nd15:000101"
```

This single string is what `AnswerContext.citation` and the `citations` dicts carry — `section_path` is **not** a separate key there (only `RetrievalHit` has it). §4.8 defines `parse_citation` to unpack it.

### 3.3 `DocumentResolver` — the single source of truth for legal effect

`services/document_resolver.py` already implements expiry/replacement/version-overlap logic. It is wired in `dependencies.py` with `version_chain_fn=graph_retriever.get_version_chain`, and reached through `ContextAssembler.merge(retrieval_hits, graph_context)`.

```python
DocumentResolver.resolve(contexts: list[AnswerContext], graph_context: GraphContext | None) -> ResolvedResult
# ResolvedResult: contexts (annotated), resolutions: list[ResolutionInfo], warnings: list[str]
# ResolutionInfo: action, reason, original_doc_id, replacement_doc_id
# action ∈ {"kept", "replaced", "superseded", "expired_warning"}
```

It decides expiry from `AnswerContext.effect_status` against `EXPIRED_STATUSES` (case-folded: "hết hiệu lực", "ngưng hiệu lực", …) and finds replacements from `REPLACED_BY` / `REPEALS` edges (`REPEALS` is reversed: source repeals target).

> **The agent must reuse this, not re-derive it.** `answer_service.py` already renders warnings off `context.resolution["action"]`; a parallel implementation inside the agent would drift from it.

---

## 4. Agent Specification (what to build)

Goal: replace the static flow with a **LangGraph ReAct Agent** that reasons and calls tools flexibly, while the static flow remains available behind a valve toggle.

### 4.1 Architecture

```
                  ┌──────────────────────────────┐
                  │   LangGraph ReAct Agent      │
                  │   (create_react_agent)       │
                  └──────────────┬───────────────┘
                                 │  tool-calling loop
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  RetrievalTool   │    │GraphValidation   │    │ WebSearchTool    │
│  (Elasticsearch) │    │Tool (Neo4j)      │    │ (Exa → TinyFish) │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

**Decision: ReAct-style agent** (`langgraph.prebuilt.create_react_agent`), not a hardcoded StateGraph. The LLM chooses tools each turn. Because the LLM may skip steps, the system prompt (§4.4) must state hard obligations, and §4.6 defines a post-hoc safety net.

Intended reasoning path (encouraged by the prompt, not hardcoded):

1. **Plan.** Agent receives the user question.
2. **Ground.** Call `retrieval_search` to find legal text by keyword/vector similarity.
3. **Expand & validate.** Feed doc ids from step 2 into `graph_validate` to find relations ("Has this document been replaced?", "Is there a circular guiding this article?") and effect status.
4. **Verify & link.** Call `web_find_source_link` to fetch an authoritative URL for each cited document (thuvienphapluat.vn, vanban.chinhphu.vn).
5. **Synthesize.** Compose the final Vietnamese answer with effect-status warnings and a linked legal-basis section.

### 4.2 New files

| Path                                               | Purpose                                                                     |
| -------------------------------------------------- | --------------------------------------------------------------------------- |
| `src/vietlegal_rag/services/agent_tools.py`        | LangChain tool definitions (factory functions bound to live services)       |
| `src/vietlegal_rag/services/agent_service.py`      | `AgentService` — builds the ReAct graph, exposes `answer` / `stream_answer` |
| `src/vietlegal_rag/services/web_search_service.py` | `ExaWebSearch`, `TinyFishWebSearch`, `FallbackWebSearch`, `NoopWebSearch`   |
| `src/vietlegal_rag/services/citation_formatter.py` | Shorten long legal titles; render the linked legal-basis block              |

Modified: `pyproject.toml`, `config.py`, `dependencies.py`, `__init__.py`, `pipe.py`.

### 4.3 Tool contracts

Tools are created by **factory functions** that close over already-built services (do not let tools construct their own clients — `dependencies.py` owns construction). Use `@tool` from `langchain_core.tools` with Pydantic `args_schema`. **Every tool returns a JSON string** (LLM-readable) and must never raise: catch all exceptions and return a JSON object with an `error` key.

```python
# services/agent_tools.py
from __future__ import annotations
import json
from typing import Any
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from retrieval_modes import RetrievalRequest


class RetrievalSearchInput(BaseModel):
    query: str = Field(description="Vietnamese legal search query. Rewrite the user's question into a keyword-rich query.")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to return.")


def make_retrieval_tool(
    retrieval_service: Any,
    base_request: RetrievalRequest,
    state: AgentRunState,
) -> StructuredTool:
    """Tool 1: retrieval_search — hybrid ES search over legal chunks."""
    ...
```

**Where `base_request` comes from:** it is exactly the `RetrievalRequest` that `AgentService.answer`/`.stream_answer` receives as its `request` argument — i.e. `pipe.py` builds it once via `build_search_request(...)` → `RetrievalRequest(**search_model.model_dump())` and passes it through unchanged. The tools inherit its `retrieval_mode`, `rerank`, `llm`, `graph`, and `filters` config; only `query` and `top_k` vary per tool call.

#### Tool 1 — `retrieval_search`

- **Wraps:** `RetrievalService.search`.
- **Input:** `query: str`, `top_k: int = 5`.
- **Behavior:** clone `base_request` via `dataclasses.replace(base_request, query=query, top_k=top_k)`. `replace` re-runs `__post_init__`, which raises `ValueError` when `rerank.enabled and rerank.candidate_k < top_k` — so clamp first: `top_k = min(top_k, base_request.rerank.candidate_k) if base_request.rerank.enabled else top_k`. (`build_search_request` sets `candidate_k = max(top_k * 4, 20)`, so the clamp rarely bites.) Note `replace` is shallow — the cloned request shares the same `RerankConfig`/`LLMConfig`/`GraphConfig` objects; treat them as read-only.
- **Returns:** JSON list of objects with keys `chunk_id`, `doc_id`, `title`, `document_number`, `legal_type`, `effect_status`, `section_path`, `citation`, `text`. Truncate `text` to 1500 chars per hit to protect the context window.
- **Side effect:** append the raw `RetrievalHit` objects to a per-request collector (see §4.5) so the final citations block and Open WebUI's `retrieval_context` stay accurate.

#### Tool 2 — `graph_validate`

- **Wraps:** `GraphRetriever.get_document_neighbors` + `DocumentResolver.resolve` (§3.3). The factory takes the `document_resolver` built in `dependencies.py` — it already carries `version_chain_fn=graph_retriever.get_version_chain`, so the tool must **not** call `get_version_chain` itself.
- **Input:** `doc_id: str` (a `doc_id` returned by `retrieval_search` — **not** a free-text title), `depth: int = 1` (clamp 1..2).
- **Behavior:**
  1. `graph_context = graph_retriever.get_document_neighbors(doc_id, depth=depth)`.
  2. Select from `state.hits` the hits whose `doc_id` matches (compare with the `doc:` prefix stripped — `DocumentResolver._clean_id` semantics), convert via `hit.to_answer_context()`.
  3. `resolved = document_resolver.resolve(those_contexts, graph_context)`.
  4. Derive `effect_verdict` from the resolver's own actions (§3.3) — **never re-scan edges yourself**:

     | `resolution["action"]` | `effect_verdict` |
     |---|---|
     | `kept` | `in_force` |
     | `replaced` | `expired` (with `replacement_doc_id`) |
     | `expired_warning` | `expired` (no replacement found) |
     | `superseded` | `superseded` |
     | no contexts matched, or `center is None` | `unknown` |

     When several contexts for the same `doc_id` disagree, take the most severe: `expired` > `superseded` > `in_force`.
  5. Store `graph_context.to_dict()` and `resolved.resolutions` on `state` so `AgentService` can populate `graph_context` / `retrieval_trace["resolutions"]` exactly like `LightRAGService` does from `context_assembler.last_resolved`.
- **Returns:** JSON object:
  ```json
  {
    "doc_id": "...",
    "center": {"id": "...", "label": "...", "properties": {...}},
    "relations": [{"source": "...", "target": "...", "type": "REPLACED_BY", "raw_label": "...", "direction": "out"}],
    "effect_verdict": "in_force" | "superseded" | "expired" | "unknown",
    "replacement_doc_id": "..." | null,
    "reason": "Tài liệu đã hết hiệu lực. Tài liệu thay thế: ...",
    "available": true
  }
  ```
  `reason` is the resolver's own Vietnamese `ResolutionInfo.reason` — pass it through verbatim so the agent's warning wording matches the static path's.
- **Degradation:** with `NoopGraphRetriever` `get_document_neighbors` returns an empty `GraphContext` and `version_chain_fn` returns `[]`, so the resolver still runs and reports `kept`/`expired_warning` from `effect_status` alone. Return `"available": false` when `center is None`, and downgrade `in_force` to `unknown` in that case — absent a graph, "no replacing edge" is not evidence of being in force. **Never raise.**

#### Tool 3 — `web_find_source_link`

- **Wraps:** `web_search_service.WebSearch` (§4.7).
- **Input:** `document_title: str` (e.g. `"Nghị định 15/2020/NĐ-CP"`), `max_results: int = 3`.
- **Behavior:** search with the title restricted to authoritative Vietnamese legal domains.
- **Returns:** JSON list of `{"title": str, "url": str, "snippet": str, "provider": "exa" | "tinyfish"}`; `[]` when no provider is configured or the search fails.

### 4.4 Agent system prompt

Vietnamese output; keep the effect-status rules already used in `answer_service.py`. Suggested content (put it in `agent_service.py` as a module constant `AGENT_SYSTEM_PROMPT`):

- Role: Vietnamese legal assistant. Answer **only** from tool results; never invent a legal basis.
- **Mandatory:** always call `retrieval_search` first. Never answer from parametric memory.
- **Mandatory:** for every document you intend to cite, call `graph_validate` with its `doc_id` before citing it.
- If `effect_verdict` is `expired` or `superseded`, you MUST warn the user explicitly and base the answer on the newer document (retrieve it via `retrieval_search` if needed), stating what changed.
- Call `web_find_source_link` once per distinct cited document to obtain the source URL. If it returns `[]`, cite without a link — do not fabricate URLs.
- Budget: at most **8 tool calls** total. If tools return nothing useful, say you could not find sufficient legal basis.
- Final answer in Vietnamese, concise, ending with the legal-basis block defined in §4.8.

### 4.5 `AgentService` contract

`AgentService` must be **drop-in compatible with `LightRAGService` as far as `pipe.py` is concerned**:

```python
class AgentService:
    def __init__(
        self,
        retrieval_service: Any,
        graph_retriever: Any,
        document_resolver: DocumentResolver,      # shared; stateless (§3.3)
        web_search: Any,
        llm: Any,                                 # langchain_openai.ChatOpenAI
        fallback_service: LightRAGService | None = None,   # §4.6
        max_iterations: int = 8,
    ) -> None: ...

    def answer(self, request: RetrievalRequest) -> dict[str, Any]: ...
    def stream_answer(self, request: RetrievalRequest) -> dict[str, Any]: ...
```

Both methods return **the same dict shape as `LightRAGService`** so `pipe.py` needs no branching after routing:

```python
# answer(...)
{"answer": str, "citations": list[dict], "retrieval_context": list[dict], "graph_context": dict, "retrieval_trace": dict}

# stream_answer(...)
{"answer_stream": Generator[str, None, None], "citations": list[dict], "retrieval_context": list[dict], "graph_context": dict, "retrieval_trace": dict}
```

Notes and constraints:

- **Per-request state.** Tools are bound to a fresh collector object per call (a small `AgentRunState` holding `hits: list[RetrievalHit]`, `graph_payload: dict`, `links: dict[doc_id -> url]`, `tool_calls: int`). Build the tools **inside** `answer`/`stream_answer`, not in `__init__`, so concurrent requests never share state. `Pipe` is a singleton and Open WebUI serves requests concurrently — this is not optional.
- **`citations`** are derived from `state.hits`, deduplicated by `(title, citation)`, enriched with `url` from `state.links` and `effect_status`/`effect_verdict` from graph validation.
- **`retrieval_context`** = `[hit.to_dict() for hit in state.hits]`.
- **`graph_context`** = the merged `GraphContext.to_dict()` from the last `graph_validate` call, or `{}`.
- **`retrieval_trace`** must include at minimum: `{"mode": "agent", "tool_calls": int, "tools_used": list[str], "iterations": int, "latency_ms": {"total": float}}`; add `"agent_error": "<code>"` on failure.

#### Streaming semantics (critical)

`pipe.py` consumes `answer_stream` as a **synchronous generator of plain text tokens** and yields them straight to the SSE channel. The LangGraph stream must therefore be adapted:

- Use `graph.stream(..., stream_mode="messages")` and yield only **final-answer AI message text deltas**. Do **not** yield tool-call arguments or tool outputs as answer text.
- Surface tool activity as **status text**, not answer text. Because `AgentService` cannot reach `__event_emitter__`, `stream_answer` accepts an optional callback:
  ```python
  def stream_answer(self, request, on_status: Callable[[str], None] | None = None) -> dict[str, Any]: ...
  ```
  `pipe.py` passes a callback that pushes descriptions onto a `queue.Queue`, drained between tokens and forwarded to `__event_emitter__` (`await` cannot happen inside a sync generator — use the queue, do not block).
- Preserve the existing `<think>` handling from `OpenAICompatibleAnswerService.stream_answer`: when a chunk carries `reasoning_content`, wrap it in `<think>…</think>`.
- **Reuse the existing failure pattern:** mirror `LightRAGService.stream_answer`'s `safe_stream_wrapper` — pull the first token inside a `try`, and on any failure fall back to `LightRAGService.stream_answer(request)` for the whole response (see §4.6).

### 4.6 Safety net & fallback

The ReAct agent may skip `graph_validate`. Add a deterministic post-check in `AgentService`:

- If `state.hits` is non-empty and `graph_validate` was never called, run **`ContextAssembler.merge([...state.hits], graph_context)`** after the agent finishes — reusing the assembler already built in `dependencies.py`, so the resolver runs exactly as it does on the static path — where `graph_context = graph_retriever.retrieve(query, [h.to_dict() for h in state.hits], request.graph.max_hops, auto_depth=request.graph.auto_depth)`. Read `context_assembler.last_resolved.resolutions` for the verdict, populate `graph_context`, and if any resolution is `replaced`/`expired_warning`/`superseded`, append the standard warning line to the answer:
  `⚠️ Lưu ý: một số căn cứ được trích dẫn có thể đã hết hiệu lực hoặc đã có phiên bản mới hơn.`
  Record `"graph_validation": "post_hoc"` in the trace (`"agent_tool"` when the agent did call `graph_validate` itself). In streaming mode this runs after the stream is exhausted, so the warning is yielded as a trailing note — before the citations block.

  **`ContextAssembler` is stateful** (`_last_resolved`) and `dependencies.py` builds exactly one. Do not share that instance across concurrent agent runs: construct a per-request `ContextAssembler(document_resolver=<the shared, stateless resolver>)` instead — `DocumentResolver` holds only `version_chain_fn` and is safe to share.
- If the agent raises, times out, or exceeds `max_iterations` with no answer text: fall back to `LightRAGService.stream_answer(request)` / `.answer(request)` and set `trace["agent_error"]`. `AgentService` therefore also takes an optional `fallback_service: LightRAGService | None`.

### 4.7 Web search service

`services/web_search_service.py`:

```python
class WebSearch(Protocol):
    def search(self, query: str, max_results: int = 3) -> list[dict[str, str]]:
        """Returns [{"title", "url", "snippet", "provider"}]; [] on failure."""
```

Implementations:

- **`ExaWebSearch(client, include_domains, num_results)`** — uses `exa_py.Exa`; call `search_and_contents(query, include_domains=[...], num_results=n, type="auto")`.
- **`TinyFishWebSearch(...)`** — the fallback provider.
- **`FallbackWebSearch(primary, secondary)`** — try `primary.search`; if it raises **or returns `[]`**, try `secondary.search`. Never raise; return `[]` when both fail.
- **`NoopWebSearch`** — returns `[]`. Used when no key is configured.

Default `include_domains`: `("thuvienphapluat.vn", "vanban.chinhphu.vn", "vbpl.vn", "datafiles.chinhphu.vn")`, overridable via `WEB_SEARCH_DOMAINS` (CSV).

**Query construction:** the tool sends the shortened document name (§4.8) plus the site hint, e.g. `"Nghị định 15/2020/NĐ-CP toàn văn"`.

### 4.8 Citations: short names + links

`services/citation_formatter.py`:

- **`parse_citation(citation: str) -> dict[str, str]`** — unpack the pipe-packed string described in §3.2 into `{"document_number", "title", "section_path", "chunk_id"}`.
  - Split on `" | "`. **Positions are not fixed** — `format_citation` drops empty parts, so a chunk with no `section_path` yields only three segments. Identify by shape, not index: the `chunk_id:`-prefixed segment last (strip the prefix), the segment matching `DOCUMENT_NUMBER_PATTERN` as `document_number`, the longest remaining segment as `title`, any leftover as `section_path`.
  - Return `""` for absent keys. Never raise on malformed input.
- **`shorten_title(title: str) -> str`** — extract the legal-type + number prefix from a long official title:
  - Input: `Nghị định 15/2020/NĐ-CP quy định xử phạt vi phạm hành chính trong lĩnh vực bưu chính, viễn thông, tần số vô tuyến điện, công nghệ thông tin và giao dịch điện tử`
  - Output: `Nghị định 15/2020/NĐ-CP`
  - Implementation: regex on the document-number pattern already used by `IntentDetector.DOCUMENT_NUMBER_PATTERN` (`\b\d{1,4}/\d{4}/[A-Z0-9-]+\b`), keep everything up to and including the match. Named codes without a number (e.g. `Bộ luật Lao động 2019`) fall back to: keep text up to the first 4-digit year, else the first 8 words. Never return an empty string — fall back to the original title.
- **`format_citations_block(citations: list[dict]) -> str`** — renders:

```markdown
📚 Căn cứ pháp lý:

- [1] [Điều 101, Nghị định 15/2020/NĐ-CP](https://vanban.chinhphu.vn/...) — Quy định về trách nhiệm sử dụng dịch vụ mạng xã hội.
- [2] [Điều 25, Bộ luật Lao động 2019](https://thuvienphapluat.vn/...) — Quy định về thời gian thử việc.
```

**Input contract.** Each `citations` dict carries at least `chunk_id`, `doc_id`, `title`, `citation` — the shape both `LightRAGService.stream_answer` and `AgentService` already produce. `section_path` is **not** a key: derive it via `parse_citation(cite["citation"])`. Optional keys the agent path adds and the static path omits: `url`, `effect_verdict`, `summary`. **All of them must be optional** — the same function serves both paths.

Rules:
- Link text is `{section_path}, {short_title}`; drop the `{section_path}, ` prefix when `section_path` is empty.
- `short_title = shorten_title(cite["title"] or parse_citation(...)["title"])`.
- No `url` → emit plain text instead of a Markdown link. Never fabricate a URL.
- Dedupe by `(short_title, section_path)`, preserving first-seen order.
- Append ` ⚠️ (Hết hiệu lực)` for `effect_verdict == "expired"`, ` ⚠️ (Đã có phiên bản mới)` for `"superseded"`. Nothing for `in_force` / `unknown` / absent.
- Trailing ` — {summary}` only when `summary` is present.
- `chunk_id` is **never rendered** — it is an internal id.
- Empty/all-filtered input → return `""` (caller yields nothing, matching today's `if citations:` guard).

> **Both paths call this** (decided). `pipe.py` currently builds the block inline as `- **[1]** {title} ({citation})`, which prints the full pipe-packed string including `chunk_id: chunk:...` — visible in the UI today. Deleting that inline loop in favour of `format_citations_block` **intentionally changes the static path's rendering**: short titles, no chunk_id leak, effect markers. See the amended acceptance criterion in §7. Retrieval, graph, resolution, and answer logic on the static path stay untouched.

### 4.9 LLM choice

**Decision: the agent reuses the existing `llm_*` valves** (`llm_base_url`, `llm_api_key`, `llm_model`) — no separate agent-LLM config. Build a `langchain_openai.ChatOpenAI(base_url=..., api_key=..., model=..., temperature=request.llm.temperature, max_tokens=request.llm.max_tokens, streaming=True)`.

- **The configured model must support OpenAI-style tool calling.** If `llm_provider != "openai-compatible"`, the agent cannot run → `dependencies.py` must not build it (warn `agent.llm_not_supported`) and `pipe.py` falls back to the static path.
- Recommended orchestration models: **Qwen-2.5-72B-Instruct**, **DeepSeek-V3/R1 (via API)**, **GPT-4o**, **Gemini 1.5 Pro** — large models are needed so the agent does not loop. Smaller models (Qwen-2.5-14B/32B) are fine for extraction but tend to mis-plan multi-tool sequences.

---

## 5. Wiring: config, dependencies, valves, pipe

### 5.1 `config.py`

Add to the frozen `Settings` dataclass and populate in `get_settings()` with the existing `_getenv_*` helpers:

| Field                                 | Env var                | Default                                                      |
| ------------------------------------- | ---------------------- | ------------------------------------------------------------ |
| `agent_enabled: bool`                 | `AGENT_ENABLED`        | `False`                                                      |
| `agent_max_iterations: int`           | `AGENT_MAX_ITERATIONS` | `8`                                                          |
| `web_search_provider: str`            | `WEB_SEARCH_PROVIDER`  | `"none"` (`"exa"`, `"tinyfish"`, `"exa_tinyfish"`, `"none"`) |
| `exa_api_key: str \| None`            | `EXA_API_KEY`          | `None`                                                       |
| `tinyfish_api_key: str \| None`       | `TINYFISH_API_KEY`     | `None`                                                       |
| `web_search_domains: tuple[str, ...]` | `WEB_SEARCH_DOMAINS`   | the four domains in §4.7                                     |

### 5.2 `dependencies.py`

- Add `agent_service: Any` to the frozen `RuntimeServices` dataclass.
- Add `_build_web_search(settings, warnings, status)` — mirrors the existing builder style: return `NoopWebSearch()` and append a warning code (`websearch.not_configured`, `websearch.init_failed`) instead of raising; set `status["web_search"]`.
- Add `_build_agent_service(settings, warnings, status, *, retrieval_service, graph_retriever, document_resolver, web_search, fallback_service)` — returns `None` when `settings.agent_enabled` is false (`status["agent"] = "disabled"`), or when the LLM is not tool-capable (`warnings.append("agent.llm_not_supported")`). Wrap construction in `try/except` honoring `settings.runtime_fallback_enabled`, exactly like `_build_answer_service`.
- Build the agent **after** `lightrag_service` so it can be passed as `fallback_service`.
- `document_resolver` is already constructed as a local in `get_runtime_services` (`DocumentResolver(version_chain_fn=...)`) — pass that same instance to both the `ContextAssembler` and `_build_agent_service`. Also expose it on `RuntimeServices` (`document_resolver: Any`) so the agent's per-request `ContextAssembler` (§4.6) can be built from it.
- **Keep warning codes client-visible and detail-free** — never embed exception text (existing invariant, see the comment in `_build_retrieval_service`).

### 5.3 `pipe.py` — `Valves`

Add (defaults from env, matching the existing style):

```python
agent_enabled: bool = Field(default=os.environ.get("AGENT_ENABLED", "false").lower() == "true",
                            description="Use the LangGraph ReAct agent instead of the static RAG flow")
agent_max_iterations: int = Field(default=8, description="Maximum agent tool-calling iterations")
web_search_provider: str = Field(default=os.environ.get("WEB_SEARCH_PROVIDER", "none"),
                                 description="Web search provider ('exa', 'tinyfish', 'exa_tinyfish', or 'none')")
exa_api_key: str = Field(default=os.environ.get("EXA_API_KEY", ""), description="Exa API key")
tinyfish_api_key: str = Field(default=os.environ.get("TINYFISH_API_KEY", ""), description="TinyFish API key")
```

Then **add every one of these to `env_mappings` in `__init__.py`** (§2.2) — booleans/ints must be stringified, which `str(value)` already does.

### 5.4 `pipe.py` — routing

**Decision: valve toggle, both paths alive.** Default `agent_enabled = false`; rollback is a valve flip.

```python
# 3. Stream pipeline phases
service = services.agent_service if (self.valves.agent_enabled and services.agent_service) else services.lightrag_service
result = service.stream_answer(request)   # same dict shape either way
```

Everything downstream (token loop, citations block, status emits) stays as-is. Keep the existing `try/except` + Vietnamese error strings verbatim. Emit a distinct status when the agent path is active (`"Agent đang phân tích câu hỏi..."`).

### 5.5 `pyproject.toml`

Add to `dependencies`:

```toml
"langchain-core>=0.3.0",
"langchain-openai>=0.2.0",
"langgraph>=0.2.0",
"exa-py>=1.0.0",
```

TinyFish: add its SDK if one is used; otherwise implement `TinyFishWebSearch` over plain HTTP with `httpx`/`requests` and document the endpoint in the module docstring.

---

## 6. Implementation Order

0. **Bug fix, independent of the agent (§3.1):** add `auto_depth: bool = True` to `NoopGraphRetriever.retrieve` in `dependencies.py` and to the `GraphRetriever` `Protocol` in `lightrag_service.py`. Land this first — it stands on its own.
1. `pyproject.toml` — add deps.
2. `services/citation_formatter.py` — `parse_citation`, `shorten_title`, `format_citations_block`. Pure functions, no I/O.
3. `services/web_search_service.py` — `WebSearch` protocol + Exa/TinyFish/Fallback/Noop.
4. `config.py` — new `Settings` fields.
5. `services/agent_tools.py` — `AgentRunState` + three tool factories.
6. `services/agent_service.py` — `AGENT_SYSTEM_PROMPT`, `AgentService.answer`, `AgentService.stream_answer`, post-hoc safety net, fallback.
7. `dependencies.py` — `_build_web_search`, `_build_agent_service`, extend `RuntimeServices`.
8. `__init__.py` — extend `env_mappings`.
9. `pipe.py` — new valves, routing, status queue for `on_status`, replace the inline `citations_md` loop with `format_citations_block`.

---

## 7. Acceptance Criteria

- `agent_enabled = false` → **retrieval, graph, resolution, and answer logic unchanged**: same `retrieval_context`, same `retrieval_trace`, same answer text as today. **Citation rendering intentionally changes** (§4.8): short titles, no `chunk_id` leak, effect markers. This supersedes any "byte-identical" reading — the static path's answer is byte-identical, its legal-basis block is not.
- `agent_enabled = true`, all services configured → answer streams token-by-token; citations carry URLs where web search resolved one.
- Neo4j down (`NoopGraphRetriever`) → agent still answers; `graph_validate` returns `"available": false` and never `in_force`; no exception reaches the user. Static path also stops emitting a spurious `lightrag_error` (step 0).
- No `EXA_API_KEY`/`TINYFISH_API_KEY` → `web_find_source_link` returns `[]`; citations render as plain text; no crash.
- Effect warnings on the agent path match the static path's wording, because both originate from `DocumentResolver.ResolutionInfo.reason` (§3.3) — no second expiry implementation exists anywhere in the diff.
- Agent error / iteration-limit hit → static flow answers instead; `retrieval_trace["agent_error"]` is set; the user still gets a response.
- Two concurrent requests never mix citations (per-request `AgentRunState`).
- Every tool returns a JSON string and never raises.

---

## 8. Testing Notes

Existing services take injected clients (`Elasticsearch`, `neo4j` driver, `OpenAI`), so tools are testable with fakes — follow the `DemoRetrievalService` / `NoopGraphRetriever` pattern in `dependencies.py` for stubs. Cover at minimum:

- `parse_citation` across: all four segments present; missing `section_path` (3 segments); missing `document_number`; garbage with no `|`.
- `shorten_title` across: numbered documents, named codes with a year, titles with neither.
- `format_citations_block`: static-path dicts (no `url`/`effect_verdict`/`summary`) and agent-path dicts (all present); `chunk_id` never appears in the output; empty input → `""`.
- `graph_validate` verdict mapping for each `ResolutionInfo.action`, plus the `center is None` → `unknown` downgrade.
- `FallbackWebSearch` — primary raises → secondary used; primary returns `[]` → secondary used; both fail → `[]`.
- `AgentService.stream_answer` fallback when the LLM raises on the first token.
- Post-hoc safety net (§4.6) fires when the agent never calls `graph_validate` and an expired document is cited.

---

## 9. Decisions Made & Open Questions

### Locked decisions (do not re-litigate)

| Topic           | Decision                                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------------------------- |
| Orchestrator    | **LangGraph ReAct** (`create_react_agent`), not a fixed StateGraph, not `AgentExecutor`                     |
| Web search      | **Exa primary, TinyFish fallback**                                                                          |
| Rollout         | **Valve toggle `agent_enabled`, default false**; static `LightRAGService` stays and doubles as the fallback |
| Agent LLM       | **Reuse existing `llm_*` valves**; must be tool-calling capable                                             |
| Answer language | Vietnamese (unchanged)                                                                                      |
| Return shape    | Identical to `LightRAGService` — `pipe.py` routing is a one-line service swap                               |
| Citation rendering | **`format_citations_block` serves both paths**; the static path's rendering changes (chunk_id stops leaking, short titles). Answer text unchanged |
| Legal effect    | **`DocumentResolver` is the only implementation**; the agent maps its `action` → `effect_verdict`, never re-scans edges |
| Noop `auto_depth` | **Fix the signature** in `NoopGraphRetriever` + the `Protocol` (step 0), rather than routing around it     |

### Open questions (choose a sensible default and note it in the PR)

1. **TinyFish API surface** — no SDK is pinned yet. Default: implement over HTTP behind the `WebSearch` protocol; swap in the SDK later without touching callers.
2. **Conversation history** — the agent currently sees only `body["messages"][-1]["content"]`, like the static flow. Multi-turn memory is out of scope for this change.
3. **Tool-call caching** — no cache across turns. If Exa latency hurts, add an in-process LRU keyed by short title inside `web_search_service.py`.
