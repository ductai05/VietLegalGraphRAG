"""Evaluate multiple-choice legal QA with and without retrieved context."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import dotenv_values, load_dotenv
from elasticsearch import Elasticsearch
from ftfy import fix_text
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    Groq,
    RateLimitError,
)
import httpx


class _SimpleNamespace:
    """Attribute-accessible dict wrapper for API response parsing."""
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if isinstance(value, dict):
                setattr(self, key, _SimpleNamespace(**value))
            elif isinstance(value, list):
                setattr(self, key, [
                    _SimpleNamespace(**item) if isinstance(item, dict) else item
                    for item in value
                ])
            else:
                setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class HttpxLLMClient:
    """Thin OpenAI-compatible client using httpx directly.

    Avoids both Groq SDK (wrong path) and OpenAI SDK (injects
    enable_thinking) issues when calling third-party endpoints.
    """

    def __init__(self, *, api_key: str, base_url: str, timeout: float = 90) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout)
        self.chat = self  # duck-type: client.chat.completions.create()
        self.completions = self

    def create(self, **kwargs: Any) -> _SimpleNamespace:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        resp = self._http.post(url, json=kwargs, headers=headers)
        if resp.status_code == 429:
            exc = RateLimitError.__new__(RateLimitError)
            exc.response = resp
            exc.status_code = 429
            raise exc
        if resp.status_code != 200:
            exc = APIStatusError.__new__(APIStatusError)
            exc.response = resp
            exc.status_code = resp.status_code
            exc.message = resp.text
            raise exc
        # Response may have streaming suffix "data: [DONE]".
        # Parse only the first JSON object from the body.
        raw = resp.text.strip()
        # Find end of the first JSON object by trying incremental parse.
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Strip trailing non-JSON lines (e.g. "data: [DONE]")
            first_line = raw.split("\n")[0].strip()
            data = json.loads(first_line)
        return _SimpleNamespace(**data)

DEFAULT_MODELS = (
    "groq/llama-3.3-70b-versatile",
    "groq/llama-3.1-8b-instant",
    "groq/qwen/qwen3-32b",
    "groq/qwen/qwen3.6-27b",
)
DEFAULT_SETUPS = ("no_rag", "hybrid_rerank", "hybrid_graph")
ANSWER_RE = re.compile(r"\b([ABCDE])\b", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=Path("output/eval_questions.json"))
    parser.add_argument(
        "--retrieval",
        type=Path,
        default=Path("output/elasticsearch_hybrid_rerank_eval.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output/llm_evaluation"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--setups", nargs="+", choices=DEFAULT_SETUPS, default=list(DEFAULT_SETUPS))
    parser.add_argument("--sparse-index", default="vietlegal_chunks_sparse_current")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", "password"))
    parser.add_argument("--neo4j-database", default=os.environ.get("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--max-hops", type=int, default=2)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-context-chars", type=int, default=4_000)
    parser.add_argument("--max-completion-tokens", type=int, default=512)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=30)
    parser.add_argument(
        "--groq-key-offset",
        type=int,
        default=0,
        help="Initial offset in the GROQ_API_KEY* pool; useful for parallel model runs.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--hydrate-only",
        action="store_true",
        help="Build the local context cache without calling Groq.",
    )
    return parser.parse_args()


def load_questions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("questions", payload)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"No questions found in {path}")
    return rows


def load_retrieval(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    details = payload.get("details")
    if not isinstance(details, list):
        raise ValueError(f"Missing retrieval details in {path}")
    return {normalize_query(row["query"]): row for row in details}


def normalize_query(value: str) -> str:
    return " ".join(value.split()).casefold()


def load_env(path: Path) -> None:
    if path.exists():
        load_dotenv(path, override=False)
    
    env_vars = {**dotenv_values(path), **os.environ}
    missing = []
    
    # Elasticsearch credentials
    if not env_vars.get("ELASTICSEARCH_URL") and not (env_vars.get("ELASTIC_CLOUD_ID") and env_vars.get("ELASTIC_API_KEY")):
        missing.append("ELASTICSEARCH_URL or (ELASTIC_CLOUD_ID + ELASTIC_API_KEY)")
        
    # LLM credentials
    if not env_vars.get("LLM_API_KEY"):
        groq_keys = [value for name, value in env_vars.items() if name.startswith("GROQ_API_KEY") and value]
        if not groq_keys:
            missing.append("LLM_API_KEY or GROQ_API_KEY*")

    if missing:
        raise ValueError(
            "Missing credentials: "
            + ", ".join(missing)
            + f". Set them in {path} or the process environment."
        )


def key_sort_value(name: str) -> tuple[int, str]:
    suffix = name.removeprefix("GROQ_API_KEY")
    return (int(suffix) if suffix.isdigit() else 1, name)


class GroqKeyPool:
    """Reloadable, deduplicated Groq key pool for long-running evaluations."""

    def __init__(self, env_file: Path, *, offset: int = 0) -> None:
        self.env_file = env_file
        self.offset = offset
        self.keys: list[tuple[str, str]] = []
        self.clients: dict[str, Groq] = {}
        self.cooldown_until: dict[str, float] = {}
        self.disabled: set[str] = set()
        self.index = 0
        self.refresh(initial=True)

    def refresh(self, *, initial: bool = False) -> None:
        old_values = dict(self.keys)
        values = {
            **{str(key): value for key, value in dotenv_values(self.env_file).items()},
            **os.environ,
        }
        
        if "LLM_API_KEY" in values and values["LLM_API_KEY"]:
            candidates = [("LLM_API_KEY", str(values["LLM_API_KEY"]))]
        else:
            candidates = sorted(
                (
                    (name, str(value))
                    for name, value in values.items()
                    if name.startswith("GROQ_API_KEY") and value
                ),
                key=lambda item: key_sort_value(item[0]),
            )
        unique: list[tuple[str, str]] = []
        seen_values: set[str] = set()
        for name, value in candidates:
            if value in seen_values:
                continue
            seen_values.add(value)
            unique.append((name, value))
        old_name = self.keys[self.index][0] if self.keys else None
        self.keys = unique
        for name, value in self.keys:
            if old_values.get(name) not in (None, value):
                self.clients.pop(name, None)
                self.disabled.discard(name)
                self.cooldown_until.pop(name, None)
        if not self.keys:
            raise ValueError(f"No LLM_API_KEY or GROQ_API_KEY* values found in {self.env_file}")
        if initial:
            self.index = self.offset % len(self.keys)
        elif old_name:
            self.index = next(
                (idx for idx, (name, _) in enumerate(self.keys) if name == old_name),
                self.index % len(self.keys),
            )
        logging.info(
            "Groq key pool has %d unique key(s); active key variable: %s",
            len(self.keys),
            self.keys[self.index][0],
        )

    @property
    def active_name(self) -> str:
        return self.keys[self.index][0]

    def client(self) -> Groq | HttpxLLMClient:
        name, key = self.keys[self.index]
        if name not in self.clients:
            values = {**dotenv_values(self.env_file), **os.environ}
            base_url = values.get("LLM_BASE_URL")
            if base_url and name == "LLM_API_KEY":
                # Use httpx directly for non-Groq endpoints.
                # Groq SDK hardcodes wrong path; OpenAI SDK injects
                # enable_thinking which Groq rejects.
                self.clients[name] = HttpxLLMClient(
                    api_key=key,
                    base_url=base_url,
                    timeout=90,
                )
            else:
                self.clients[name] = Groq(api_key=key, max_retries=0, timeout=90)
        return self.clients[name]

    def disable_active(self) -> None:
        self.disabled.add(self.active_name)

    def rotate(self, *, cooldown_seconds: float = 0.0) -> tuple[str, float]:
        active = self.active_name
        if cooldown_seconds > 0:
            self.cooldown_until[active] = time.monotonic() + cooldown_seconds
        self.refresh()
        now = time.monotonic()
        for step in range(1, len(self.keys) + 1):
            index = (self.index + step) % len(self.keys)
            name = self.keys[index][0]
            if name in self.disabled:
                continue
            if self.cooldown_until.get(name, 0.0) <= now:
                self.index = index
                return name, 0.0
        available = [
            (self.cooldown_until.get(name, now), index, name)
            for index, (name, _) in enumerate(self.keys)
            if name not in self.disabled
        ]
        if not available:
            raise RuntimeError("All configured Groq API keys are disabled")
        ready_at, index, name = min(available)
        self.index = index
        return name, max(0.0, ready_at - now)


def batched(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def hydrate_contexts(
    client: Elasticsearch,
    retrieval_by_query: dict[str, dict[str, Any]],
    *,
    index: str,
    top_k: int,
) -> dict[str, dict[str, Any]]:
    chunk_ids = list(
        dict.fromkeys(
            str(chunk_id)
            for row in retrieval_by_query.values()
            for chunk_id in row.get("top_chunk_ids", [])[:top_k]
        )
    )
    chunks: dict[str, dict[str, Any]] = {}
    source_fields = [
        "chunk_id",
        "chunk_text",
        "contextual_text",
        "title",
        "document_number",
        "legal_type",
        "section_path",
        "doc_id",
    ]
    for batch in batched(chunk_ids, 500):
        response = client.search(
            index=index,
            size=len(batch),
            query={"terms": {"chunk_id": batch}},
            source_includes=source_fields,
        )
        for hit in response["hits"]["hits"]:
            source = dict(hit.get("_source") or {})
            for field in (
                "chunk_text",
                "contextual_text",
                "title",
                "document_number",
                "legal_type",
            ):
                if isinstance(source.get(field), str):
                    source[field] = fix_text(source[field])
            if isinstance(source.get("section_path"), list):
                source["section_path"] = [
                    fix_text(str(value)) for value in source["section_path"]
                ]
            chunk_id = source.get("chunk_id")
            if chunk_id:
                chunks[str(chunk_id)] = source
    missing = sorted(set(chunk_ids) - set(chunks))
    if missing:
        raise RuntimeError(
            f"Could not hydrate {len(missing)} of {len(chunk_ids)} retrieved chunks "
            f"from {index}; first missing ID: {missing[0]}"
        )
    return chunks


def hydrate_graph_contexts(
    elastic: Elasticsearch,
    driver: Any,
    neo4j_database: str,
    questions: list[dict[str, Any]],
    retrieval: dict[str, dict[str, Any]],
    chunks: dict[str, dict[str, Any]],
    *,
    index: str,
    top_k: int,
    max_hops: int,
) -> dict[str, list[str]]:
    """Perform graph expansion for each question and hydrate the neighbor chunks."""
    backend_path = str(Path(__file__).resolve().parent.parent.parent / "src" / "backend")
    services_path = str(Path(__file__).resolve().parent.parent.parent / "src" / "backend" / "services")
    if backend_path not in sys.path:
        sys.path.append(backend_path)
    if services_path not in sys.path:
        sys.path.append(services_path)
    try:
        from services.graph_retriever import GraphRetriever
        from services.elasticsearch_retriever import ElasticsearchGraphChunkFetcher
    except ImportError:
        raise RuntimeError("Failed to import GraphRetriever. Ensure src/backend is reachable.")

    fetcher = ElasticsearchGraphChunkFetcher(elastic, index=index, per_doc_size=1)
    retriever = GraphRetriever(driver, database=neo4j_database, chunk_fetcher=fetcher)

    query_graph_chunk_ids: dict[str, list[str]] = {}

    for q in questions:
        q_id = q["question_id"]
        query_text = q["question"]
        row = retrieval.get(normalize_query(query_text))
        if not row:
            continue
        
        top_ids = [str(cid) for cid in row["top_chunk_ids"][:top_k]]
        base_doc_ids = []
        for cid in top_ids:
            if cid in chunks and chunks[cid].get("doc_id"):
                base_doc_ids.append(str(chunks[cid]["doc_id"]))
        
        expanded_chunks = []
        seen_chunk_ids = set(top_ids)
        for doc_id in set(base_doc_ids):
            graph_context = retriever.get_document_neighbors(doc_id, depth=max_hops)
            related_docs = []
            for node in graph_context.nodes:
                node_doc_id = node.properties.get("doc_id") if hasattr(node, "properties") else None
                if not node_doc_id and hasattr(node, "id") and str(node.id).startswith("doc:"):
                    node_doc_id = str(node.id).split(":", 1)[1]
                if node_doc_id:
                    related_docs.append({"doc_id": str(node_doc_id)})
            
            answer_contexts = fetcher(query=query_text, related_documents=related_docs)
            for ac in answer_contexts:
                cid = str(ac.chunk_id)
                if cid not in seen_chunk_ids:
                    seen_chunk_ids.add(cid)
                    chunks[cid] = {
                        "chunk_id": cid,
                        "chunk_text": ac.text,
                        "doc_id": ac.doc_id,
                        "title": ac.title,
                        "citation": ac.citation,
                    }
                    expanded_chunks.append(cid)
                    
        query_graph_chunk_ids[q_id] = expanded_chunks

    return query_graph_chunk_ids


def build_context(
    chunk_ids: list[str],
    chunks: dict[str, dict[str, Any]],
    *,
    max_chars: int,
) -> tuple[str, list[str], bool]:
    blocks: list[str] = []
    included: list[str] = []
    truncated = False
    if len(chunk_ids) >= 3:
        remaining_weight = 0.5 / (len(chunk_ids) - 3) if len(chunk_ids) > 3 else 0.0
        weights = [0.25, 0.15, 0.10] + [remaining_weight] * (len(chunk_ids) - 3)
    else:
        weights = [1.0 / max(len(chunk_ids), 1)] * len(chunk_ids)
    for rank, chunk_id in enumerate(chunk_ids, start=1):
        source = chunks[str(chunk_id)]
        text = str(source.get("chunk_text") or source.get("contextual_text") or "").strip()
        section = source.get("section_path") or []
        if isinstance(section, list):
            section = " > ".join(str(item) for item in section)
        header = " | ".join(
            item
            for item in [
                f"Nguồn {rank}",
                f"chunk_id={chunk_id}",
                str(source.get("document_number") or ""),
                str(source.get("title") or ""),
                str(section or ""),
            ]
            if item
        )
        prefix = f"[{header}]\n"
        per_chunk_budget = max(200, int(max_chars * weights[rank - 1]))
        text_budget = max(0, per_chunk_budget - len(prefix) - 2)
        if len(text) > text_budget:
            marker = "\n...[đã lược bớt phần giữa]...\n"
            available = max(0, text_budget - len(marker))
            head_chars = available // 2
            tail_chars = available - head_chars
            text = (
                text[:head_chars].rstrip()
                + marker
                + (text[-tail_chars:].lstrip() if tail_chars else "")
            )
            truncated = True
        block = prefix + text
        blocks.append(block)
        included.append(str(chunk_id))
    joined = "\n\n".join(blocks)
    if len(joined) > max_chars:
        joined = joined[:max_chars]
        truncated = True
    return joined, included, truncated


def choices_text(question: dict[str, Any]) -> str:
    choices = question["choices"]
    return "\n".join(f"{label}. {choices[label]}" for label in ("A", "B", "C", "D"))


def build_prompt(
    question: dict[str, Any],
    setup: str,
    context: str = "",
    valid_chunk_ids: list[str] | None = None,
) -> str:
    choices_str = choices_text(question)
    if setup != "no_rag":
        choices_str += "\nE. Không đủ thông tin trong tài liệu tham khảo"
        
    common = (
        "Trả lời câu hỏi trắc nghiệm pháp luật Việt Nam dưới đây. "
        f"Chỉ chọn một đáp án {'A, B, C, D hoặc E' if setup != 'no_rag' else 'A, B, C hoặc D'}. "
        "Không giải thích dài dòng. Trả về đúng một JSON object có dạng "
        '{"answer":"A","cited_chunk_ids":[]}.\n\n'
        f"Câu hỏi: {question['question']}\n"
        f"{choices_str}"
    )
    if setup == "no_rag":
        return (
            common
            + "\n\nKhông có tài liệu truy xuất. cited_chunk_ids phải là mảng rỗng."
        )
    allowed = ", ".join(valid_chunk_ids or [])
    return (
        common
        + "\n\nChỉ dựa trên các nguồn truy xuất bên dưới. "
        "cited_chunk_ids phải chứa chunk_id của nguồn trực tiếp hỗ trợ đáp án, "
        "và chỉ được dùng ID trong danh sách cho phép.\n"
        "Nếu các nguồn truy xuất KHÔNG chứa đủ thông tin để trả lời câu hỏi, bạn BẮT BUỘC phải chọn đáp án E thay vì cố đoán.\n\n"
        f"Chunk ID cho phép: {allowed}\n\nNguồn truy xuất:\n{context}"
    )


def parse_response(content: str) -> tuple[str | None, list[str], bool]:
    text = (content or "").strip()

    # Remove <think>...</think> block if present
    # We use re.sub with re.DOTALL to match across newlines
    # If the response was truncated and missing </think>, we try to remove everything after <think>
    if "<think>" in text:
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        if "<think>" in text:  # Unclosed tag
            text = text.split("<think>")[0].strip()

    json_str = text
    json_match = re.search(r'```(?:json)?(.*?)```', text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end >= start:
            json_str = text[start:end+1]

    try:
        payload = json.loads(json_str)
        answer = str(payload.get("answer", "")).strip().upper()
        citations = payload.get("cited_chunk_ids") or []
        if answer in {"A", "B", "C", "D", "E"} and isinstance(citations, list):
            return answer, [str(value) for value in citations], True
    except (json.JSONDecodeError, TypeError, ValueError):
        # try to find a valid JSON object within the text using regex
        json_objs = re.findall(r'\{[^{}]*\"answer\"\s*:[^{}]*\}', text)
        if json_objs:
            try:
                payload = json.loads(json_objs[-1])
                answer = str(payload.get("answer", "")).strip().upper()
                citations = payload.get("cited_chunk_ids") or []
                if answer in {"A", "B", "C", "D", "E"} and isinstance(citations, list):
                    return answer, [str(value) for value in citations], True
            except Exception:
                pass

    match = ANSWER_RE.search(text)
    return (match.group(1).upper() if match else None), [], False


def request_completion(
    key_pool: GroqKeyPool,
    *,
    model: str,
    prompt: str,
    max_completion_tokens: int,
    max_retries: int,
    seed: int,
) -> tuple[Any, int, str]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_completion_tokens": max_completion_tokens,
        "seed": seed,
    }
    if "qwen3.6-27b" in model.lower():
        kwargs["max_completion_tokens"] = max(max_completion_tokens, 4096)
    # Groq's Qwen3 thinking models reject response_format:json_object
    # and reasoning_format/reasoning_effort. Use plain text and parse.
    if "qwen3" not in model.lower():
        kwargs["response_format"] = {"type": "json_object"}
    json_fallback_used = False
    for attempt in range(max_retries + 1):
        try:
            key_name = key_pool.active_name
            response = key_pool.client().chat.completions.create(**kwargs)
            return response, attempt, key_name
        except (RateLimitError, APIConnectionError, APITimeoutError, APIStatusError, httpx.HTTPError) as exc:
            if attempt >= max_retries:
                raise
            status_code = getattr(exc, "status_code", None)
            if (
                isinstance(exc, (APIStatusError, httpx.HTTPStatusError))
                and status_code == 400
                and "json_validate_failed" in str(exc)
                and not json_fallback_used
            ):
                logging.warning(
                    "JSON mode failed for %s; retrying once in plain text mode",
                    model,
                )
                kwargs.pop("response_format", None)
                json_fallback_used = True
                continue
            if isinstance(exc, (APIStatusError, httpx.HTTPStatusError)) and status_code is not None and 400 <= status_code < 500:
                if status_code == 401:
                    logging.warning("Disabling rejected API key variable %s", key_pool.active_name)
                    key_pool.disable_active()
                    next_name, wait = key_pool.rotate()
                    logging.warning("Rotated to %s after authentication failure", next_name)
                    if wait:
                        time.sleep(wait)
                    continue
                if not isinstance(exc, RateLimitError):
                    logging.warning("APIError status %s for %s, retrying anyway...", status_code, model)
            if (
                isinstance(exc, (APIStatusError, httpx.HTTPStatusError))
                and status_code == 413
                and "Request too large" in str(exc)
            ):
                raise
            retry_after = None
            response = getattr(exc, "response", None)
            if response is not None:
                retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else min(60.0, 2**attempt)
            except ValueError:
                delay = min(60.0, 2**attempt)
            if isinstance(exc, RateLimitError):
                next_name, wait = key_pool.rotate(cooldown_seconds=delay)
                logging.warning(
                    "Rate limited on %s; rotated to %s%s",
                    model,
                    next_name,
                    f", waiting {wait:.1f}s" if wait else "",
                )
                if wait:
                    time.sleep(wait + random.random())
            else:
                delay += random.random()
                logging.warning(
                    "LLM request failed for %s (attempt %d/%d); retrying in %.1fs",
                    model,
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)
    raise AssertionError("unreachable")


def existing_keys(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") == "ok":
            keys.add((row["question_id"], row["model"], row["setup"]))
    return keys


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def paired_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    by_key: dict[tuple[str, str], dict[str, bool]] = defaultdict(dict)
    for row in rows:
        if row.get("status") == "ok":
            by_key[(row["model"], row["question_id"])][row["setup"]] = row["correct"]
    counts = {"both_correct": 0, "both_wrong": 0, "rag_only": 0, "no_rag_only": 0}
    for pair in by_key.values():
        if set(pair) != set(DEFAULT_SETUPS):
            continue
        no_rag, rag = pair["no_rag"], pair["hybrid_rerank"]
        if no_rag and rag:
            counts["both_correct"] += 1
        elif not no_rag and not rag:
            counts["both_wrong"] += 1
        elif rag:
            counts["rag_only"] += 1
        else:
            counts["no_rag_only"] += 1
    return counts


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row.get("status") == "ok"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in valid:
        groups[(row["model"], row["setup"])].append(row)
    results = {}
    for (model, setup), subset in sorted(groups.items()):
        by_type = {}
        for question_type in sorted({row["question_type"] for row in subset}):
            typed = [row for row in subset if row["question_type"] == question_type]
            by_type[question_type] = {
                "questions": len(typed),
                "accuracy": safe_mean([float(row["correct"]) for row in typed]),
            }
        item = {
            "questions": len(subset),
            "accuracy": safe_mean([float(row["correct"]) for row in subset]),
            "valid_json_rate": safe_mean([float(row["valid_json"]) for row in subset]),
            "mean_latency_seconds": safe_mean([row["latency_seconds"] for row in subset]),
            "prompt_tokens": sum(row.get("prompt_tokens", 0) for row in subset),
            "completion_tokens": sum(row.get("completion_tokens", 0) for row in subset),
            "by_question_type": by_type,
        }
        if setup in ("hybrid_rerank", "hybrid_graph"):
            item.update(
                {
                    "retrieval_hit_rate": safe_mean(
                        [float(row["retrieval_hit"]) for row in subset]
                    ),
                    "citation_validity": safe_mean(
                        [float(row["citation_valid"]) for row in subset]
                    ),
                    "gold_citation_rate": safe_mean(
                        [float(row["cites_gold"]) for row in subset]
                    ),
                    "accuracy_when_retrieval_hit": safe_mean(
                        [
                            float(row["correct"])
                            for row in subset
                            if row["retrieval_hit"]
                        ]
                    ),
                    "accuracy_when_retrieval_miss": safe_mean(
                        [
                            float(row["correct"])
                            for row in subset
                            if not row["retrieval_hit"]
                        ]
                    ),
                    "refusal_rate": safe_mean(
                        [
                            1.0 if row.get("predicted_answer") == "E" else 0.0
                            for row in subset
                        ]
                    ),
                    "refusal_when_retrieval_miss": safe_mean(
                        [
                            1.0 if row.get("predicted_answer") == "E" else 0.0
                            for row in subset
                            if not row["retrieval_hit"]
                        ]
                    ),
                    "hallucination_when_retrieval_miss": safe_mean(
                        [
                            1.0 if row.get("predicted_answer") in {"A", "B", "C", "D"} and not row["correct"] else 0.0
                            for row in subset
                            if not row["retrieval_hit"]
                        ]
                    ),
                }
            )
        results.setdefault(model, {})[setup] = item
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "successful_requests": len(valid),
        "failed_requests": len(rows) - len(valid),
        "results": results,
        "paired_outcomes": paired_counts(valid),
    }


def usage_value(usage: Any, name: str) -> int:
    return int(getattr(usage, name, 0) or 0) if usage is not None else 0


def main() -> None:
    args = parse_args()
    if not args.env_file.exists() and Path("env").exists():
        args.env_file = Path("env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.top_k <= 0 or args.max_context_chars <= 0:
        raise ValueError("--top-k and --max-context-chars must be positive")
    load_env(args.env_file)
    questions = load_questions(args.questions)
    retrieval = load_retrieval(args.retrieval)
    selected = questions[args.start_index :]
    if args.limit is not None:
        selected = selected[: args.limit]
        
    models_to_run = args.models

    es_url = os.environ.get("ELASTICSEARCH_URL")
    if es_url:
        es_api_key = os.environ.get("ELASTICSEARCH_API_KEY") or os.environ.get("ELASTIC_API_KEY")
        elastic = Elasticsearch(
            hosts=[es_url],
            api_key=es_api_key,
            verify_certs=os.environ.get("ELASTICSEARCH_VERIFY_CERTS", "true").lower() == "true",
            request_timeout=60,
        )
    else:
        elastic = Elasticsearch(
            cloud_id=os.environ["ELASTIC_CLOUD_ID"],
            api_key=os.environ["ELASTIC_API_KEY"],
            request_timeout=60,
        )
    query_graph_chunk_ids: dict[str, list[str]] = {}
    try:
        chunks = hydrate_contexts(
            elastic,
            retrieval,
            index=args.sparse_index,
            top_k=args.top_k,
        )
        if "hybrid_graph" in args.setups:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
            try:
                logging.info("Hydrating graph contexts...")
                query_graph_chunk_ids = hydrate_graph_contexts(
                    elastic=elastic,
                    driver=driver,
                    neo4j_database=args.neo4j_database,
                    questions=selected,
                    retrieval=retrieval,
                    chunks=chunks,
                    index=args.sparse_index,
                    top_k=args.top_k,
                    max_hops=args.max_hops,
                )
            finally:
                driver.close()
    finally:
        elastic.close()

    contexts_path = args.output_dir / "contexts.jsonl"
    contexts_path.parent.mkdir(parents=True, exist_ok=True)
    context_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for question in questions:
        row = retrieval.get(normalize_query(question["question"]))
        if not row:
            logging.warning(f"No retrieval result for {question['question_id']}. Skipping.")
            continue
        for setup in args.setups:
            if setup == "no_rag":
                continue
            
            top_ids = [str(value) for value in row["top_chunk_ids"][: args.top_k]]
            if setup == "hybrid_graph":
                top_ids.extend(query_graph_chunk_ids.get(question["question_id"], []))
                
            text, included_ids, truncated = build_context(
                top_ids,
                chunks,
                max_chars=args.max_context_chars,
            )
            context_rows[(setup, question["question_id"])] = {
                "question_id": question["question_id"],
                "top_chunk_ids": top_ids,
                "included_chunk_ids": included_ids,
                "context": text,
                "truncated": truncated,
            }
    
    with contexts_path.open("w", encoding="utf-8") as handle:
        for question in questions:
            for setup in args.setups:
                if setup == "no_rag":
                    continue
                row_data = context_rows.get((setup, question["question_id"]))
                if not row_data:
                    continue
                handle.write(json.dumps({"setup": setup, **row_data}, ensure_ascii=False) + "\n")
    logging.info("Wrote hydrated contexts to %s", contexts_path)
    if args.hydrate_only:
        return

    results_path = args.output_dir / "responses.jsonl"
    completed = set() if args.no_resume else existing_keys(results_path)
    key_pool = GroqKeyPool(args.env_file, offset=args.groq_key_offset)
    total = len(selected) * len(models_to_run) * len(args.setups)
    done = 0
    for model in models_to_run:
        for setup in args.setups:
            for question in selected:
                key = (question["question_id"], model, setup)
                done += 1
                if key in completed:
                    continue
                if setup == "no_rag":
                    context_str = ""
                    included_ids_list = []
                else:
                    context_row = context_rows.get((setup, question["question_id"]))
                    if not context_row:
                        continue
                    context_str = context_row["context"]
                    included_ids_list = context_row["included_chunk_ids"]

                prompt = build_prompt(
                    question,
                    setup,
                    context_str,
                    included_ids_list,
                )
                started = time.perf_counter()
                base = {
                    "question_id": question["question_id"],
                    "question": question["question"],
                    "question_type": question.get("question_type", "unknown"),
                    "difficulty": question.get("difficulty", "unknown"),
                    "gold_answer": question["answer"],
                    "model": model,
                    "setup": setup,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    response, retries, key_name = request_completion(
                        key_pool,
                        model=model,
                        prompt=prompt,
                        max_completion_tokens=args.max_completion_tokens,
                        max_retries=args.max_retries,
                        seed=args.seed,
                    )
                    content = response.choices[0].message.content or ""
                    answer, cited_ids, valid_json = parse_response(content)
                    allowed_ids = set(included_ids_list)
                    gold_ids = set(question.get("evidence", {}).get("chunk_ids") or [])
                    retrieval_hit = bool(allowed_ids & gold_ids)
                    usage = getattr(response, "usage", None)
                    result = {
                        **base,
                        "status": "ok",
                        "predicted_answer": answer,
                        "correct": answer == question["answer"],
                        "cited_chunk_ids": cited_ids,
                        "valid_json": valid_json,
                        "citation_valid": (
                            setup in ("hybrid_rerank", "hybrid_graph")
                            and bool(cited_ids)
                            and set(cited_ids).issubset(allowed_ids)
                        ),
                        "cites_gold": (
                            setup in ("hybrid_rerank", "hybrid_graph")
                            and bool(set(cited_ids) & gold_ids)
                        ),
                        "retrieval_hit": retrieval_hit,
                        "included_chunk_ids": included_ids_list,
                        "context_truncated": context_row["truncated"] if setup != "no_rag" else False,
                        "latency_seconds": round(time.perf_counter() - started, 4),
                        "prompt_tokens": usage_value(usage, "prompt_tokens"),
                        "completion_tokens": usage_value(usage, "completion_tokens"),
                        "total_tokens": usage_value(usage, "total_tokens"),
                        "retries": retries,
                        "groq_key_variable": key_name,
                        "raw_response": content,
                    }
                except Exception as exc:
                    result = {
                        **base,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "latency_seconds": round(time.perf_counter() - started, 4),
                    }
                    logging.exception("Failed %s %s %s", model, setup, question["question_id"])
                append_jsonl(results_path, result)
                logging.info(
                    "[%d/%d] %s %s %s: %s",
                    done,
                    total,
                    model,
                    setup,
                    question["question_id"],
                    result["status"],
                )

    rows = load_jsonl(results_path)
    summary = summarize(rows)
    summary["configuration"] = {
        "models": models_to_run,
        "setups": args.setups,
        "top_k": args.top_k,
        "max_context_chars": args.max_context_chars,
        "seed": args.seed,
        "questions": len(selected),
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logging.info("Wrote summary to %s", summary_path)


if __name__ == "__main__":
    main()
