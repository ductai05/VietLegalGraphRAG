# VietLegal GraphRAG — Run & Test Tutorial

How to start the app locally and verify the LangGraph ReAct agent works.

For architecture and the agent spec, see [developer_guide.md](developer_guide.md).

---

## 1. What you actually start

There is **no separate frontend and backend process**. `src/infra/docker-compose.yml`
builds one container (`open-webui`) that serves both:

- the SvelteKit frontend (built at image build time from `src/open-webui/`),
- the FastAPI backend, which imports the RAG core (`src/vietlegal_rag/`) as a
  Pipe Function.

Elasticsearch and Neo4j are **external** — the container connects to them over
the network using env vars. Nothing spins them up for you.

---

## 2. Configure

```bash
cp src/infra/.env.example src/infra/.env
```

Edit `src/infra/.env`. Minimum for a useful run:

| Variable | Notes |
|---|---|
| `WEBUI_ADMIN_EMAIL` / `WEBUI_ADMIN_PASSWORD` | Auto-provisions the admin account |
| `WEBUI_SECRET_KEY` | `openssl rand -hex 32` |
| `ELASTICSEARCH_URL` / `ELASTICSEARCH_API_KEY` | Without these you get `DemoRetrievalService` (one fake chunk) |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Without a password you get `NoopGraphRetriever` (empty graph) |
| `LLM_PROVIDER` | `extractive` (no LLM) or `openai-compatible` |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | Required when `openai-compatible` |

Everything missing degrades to a warning rather than a crash, so the app starts
even half-configured. That is deliberate — it also means **a green startup does
not mean things are wired**. Check the status codes in §5.

## 3. Start

```bash
docker compose --env-file src/infra/.env -f src/infra/docker-compose.yml up --build
```

Open <http://localhost:8080> (or `FRONTEND_PORT`) and log in with
`WEBUI_ADMIN_EMAIL` / `WEBUI_ADMIN_PASSWORD`.

On boot, `src/infra/scripts/init_pipe.py` uploads `pipe.py` and activates a
virtual model named **VietLegal RAG**. Pick it in the model dropdown — if you
chat with any other model you are talking to a plain LLM, not the RAG pipeline.

First query is slow: `Pipe.__init__` pre-warms the embedding model in a
background thread.

---

## 4. Turn the agent on

The agent is **off by default** (`agent_enabled = false`); the static
retrieve → graph → answer flow runs instead.

In `src/infra/.env`:

```dotenv
AGENT_ENABLED=true
AGENT_MAX_ITERATIONS=8

# Required — the agent needs OpenAI-style tool calling.
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://your-endpoint/v1
LLM_API_KEY=sk-...
LLM_MODEL=qwen2.5-72b-instruct

# Optional: source links in citations. Omit and citations render as plain text.
WEB_SEARCH_PROVIDER=exa
EXA_API_KEY=...
```

Then restart:

```bash
docker compose --env-file src/infra/.env -f src/infra/docker-compose.yml up -d --force-recreate
```

> **Restart is not optional.** `Pipe._services` and `get_runtime_services()`
> (an `lru_cache`) both cache the first build for the container's lifetime.
> Editing valves in the Admin Panel after the first query will *not* take
> effect until the container restarts. This bites people who flip
> `agent_enabled` in the UI and conclude the agent is broken.

Use a large model. Qwen-2.5-72B, DeepSeek-V3/R1, GPT-4o, and Gemini 1.5 Pro
plan multi-tool sequences reliably; 14B/32B models tend to mis-plan and burn
the iteration budget.

If `LLM_PROVIDER` is not `openai-compatible`, or the API key is missing, the
agent is **never built** (`agent.llm_not_supported`) and the pipe silently
stays on the static path. That is the intended behaviour, not a failure.

---

## 5. Verify it works

### 5.1 Run the test suite

```bash
python -m pytest tests -q
```

Expect **267 passed, 1 failed, 3 skipped**. The one failure,
`test_process_image_passes_language_hints_as_request_context`, is a
pre-existing OCR failure unrelated to the agent. Anything else failing is a
real regression.

Agent-specific tests only:

```bash
python -m pytest tests/test_agent_service.py tests/test_citation_formatter.py tests/test_web_search_service.py -q
```

These are hermetic — no Elasticsearch, Neo4j, LLM, or Exa calls — so they pass
on a laptop with nothing configured.

### 5.2 Confirm the agent is actually live

Ask the model a legal question and watch the **status line above the answer**.

Static path:

```
Đang tìm kiếm tài liệu & đồ thị...
```

Agent path:

```
Agent đang phân tích câu hỏi...
Đang tìm kiếm văn bản pháp luật...      <- retrieval_search
Đang kiểm tra hiệu lực văn bản...       <- graph_validate
Đang tìm nguồn trích dẫn chính thống... <- web_find_source_link
```

If you only ever see the static line, the agent was not built — check the
container logs for `agent.llm_not_supported` or `agent.init_failed`.

Tool statuses appear in a burst when the first answer token arrives, not live
during the tool loop. That is expected: the pipe drains the status queue
between tokens, and no tokens exist until the agent finishes calling tools.

### 5.3 Check the citation block

Both paths now end with a rendered legal-basis block:

```markdown
---
**📚 Căn cứ pháp lý:**
- **[1]** [Điều 101, Nghị định 15/2020/NĐ-CP](https://vanban.chinhphu.vn/...)
```

Signals it is working:

- **Short titles.** `Nghị định 15/2020/NĐ-CP`, not the full 200-character official title.
- **No `chunk_id: chunk:...` leak.** If you see one, `format_citations_block` is not being used.
- **Links** only on the agent path, and only when web search resolved one. Never invented.
- **`⚠️ (Hết hiệu lực)`** / **`⚠️ (Đã có phiên bản mới)`** on superseded documents.

This block changed for the static path too. The static path's **answer text**
is unchanged; only its citation rendering differs.

### 5.4 Check the degradation paths

These are the ones worth testing, because they are what break in production.

| Scenario | Expected |
|---|---|
| Unset `NEO4J_PASSWORD` | Agent still answers. `graph_validate` returns `"available": false` and **never** `in_force`. No error reaches the user. |
| Unset `EXA_API_KEY` | `web_find_source_link` returns `[]`. Citations render as plain text. No crash. |
| Point `LLM_BASE_URL` at a dead host | Static flow answers instead; `retrieval_trace["agent_error"]` is set. The user still gets a response. |
| `WEB_SEARCH_PROVIDER=tinyfish` | Warns `websearch.unknown_provider`, degrades to no web search. TinyFish is not implemented — see the note below. |

In every case the user gets an answer. If a Vietnamese error string reaches the
chat, something is genuinely wrong.

### 5.5 Read the warning codes

Warnings are deliberately detail-free (they are client-visible and must never
leak exception text). Grep the container logs:

```bash
docker compose -f src/infra/docker-compose.yml logs open-webui | grep -iE "agent\.|websearch\.|neo4j\.|elasticsearch\."
```

| Code | Meaning |
|---|---|
| `agent.llm_not_supported` | `LLM_PROVIDER` is not `openai-compatible`, or no API key. Agent not built. |
| `agent.init_failed` | Construction blew up — usually a missing dependency. |
| `websearch.not_configured` | `WEB_SEARCH_PROVIDER=exa` but `EXA_API_KEY` is empty. |
| `websearch.unknown_provider` | Provider is neither `exa` nor `none`. |
| `websearch.init_failed` | Exa client construction failed. |
| `neo4j.not_configured` | No password → `NoopGraphRetriever`. |
| `elasticsearch.not_configured` | → `DemoRetrievalService`, one fake chunk. |

`retrieval_trace` (with `mode`, `tool_calls`, `tools_used`, `graph_validation`)
is returned by the service but **not rendered in the UI**. Read it from logs or
a debugger, not the chat window.

---

## 6. Known divergences from the spec

- **TinyFish is not implemented.** `developer_guide.md` §4.7/§9 lists it as a
  locked decision, but no SDK is pinned and its API is unknown, so it was
  dropped. `WEB_SEARCH_PROVIDER` accepts `exa` or `none`. The
  `FallbackWebSearch(primary, secondary)` seam is still there for a future
  second provider.
- **`shorten_title` does not reuse `IntentDetector.DOCUMENT_NUMBER_PATTERN`**
  as §4.8 says to. That pattern's ASCII-only `[A-Z0-9-]` class does not match
  `15/2020/NĐ-CP` — the guide's own example. `citation_formatter` uses
  `[A-ZĐ0-9-]`. `IntentDetector` still has the blind spot.
