// Backend integration for Aurora / VietLegalGraphRAG.
// Logic ported verbatim from the original app.js so the API contract is unchanged.

const REQUEST_TIMEOUT_MS = 30000;

export function resolveApiBase() {
  if (typeof window !== "undefined" && window.AURORA_API_BASE) {
    return window.AURORA_API_BASE;
  }
  const host = typeof window !== "undefined" ? window.location.hostname : "";
  if (host === "localhost" || host === "127.0.0.1") {
    return "http://localhost:8000";
  }
  return "/api";
}

export const API_BASE = resolveApiBase();

async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("request.timeout");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

async function ensureOk(response) {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Backend returned ${response.status}`);
  }
}

export async function requestAnswer(text) {
  const response = await fetchWithTimeout(`${API_BASE}/answer`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      "query": text,
      "retrieval_mode": "hybrid",
      "top_k": 5,
      "filters": {},
      "include_trace": true,
      "rerank": {
        "enabled": true,
        "model": "rerank-2.5",
        "candidate_k": 20,
        "batch_size": 8,
        "device": "auto",
        "timeout_ms": 30000
      },
      "graph": {
        "enabled": true,
        "use_lightrag": true,
        "max_hops": 1
      },
      "llm": {
        "temperature": 0.2,
        "max_context_chunks": 8
      }
    })
  });

  await ensureOk(response);
  return response.json();
}

export async function requestOcr(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetchWithTimeout(`${API_BASE}/documents/ocr`, {
    method: "POST",
    body: formData
  });
  await ensureOk(response);
  return response.json();
}
