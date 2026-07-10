const menuToggle = document.querySelector("[data-menu-toggle]");
const nav = document.querySelector("[data-nav]");

if (menuToggle && nav) {
  menuToggle.addEventListener("click", () => {
    const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
    menuToggle.setAttribute("aria-expanded", String(!isOpen));
    nav.classList.toggle("is-open", !isOpen);
  });

  nav.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      menuToggle.setAttribute("aria-expanded", "false");
      nav.classList.remove("is-open");
    }
  });
}

const chatForm = document.querySelector("#chat-form");
const chatInput = document.querySelector("#chat-input");
const messageList = document.querySelector("#message-list");
const promptButtons = document.querySelectorAll("[data-prompt]");
const handoffButtons = document.querySelectorAll("[data-handoff]");
const ocrForm = document.querySelector("#ocr-form");
const ocrFile = document.querySelector("#ocr-file");
const REQUEST_TIMEOUT_MS = 30000;
const API_BASE = resolveApiBase();

function resolveApiBase() {
  if (window.AURORA_API_BASE) {
    return window.AURORA_API_BASE;
  }
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") {
    return "http://localhost:8000";
  }
  return "/api";
}

const revealItems = document.querySelectorAll(".reveal");

if (revealItems.length && "IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.18 });

  revealItems.forEach((item) => observer.observe(item));
} else {
  revealItems.forEach((item) => item.classList.add("is-visible"));
}

const statRows = document.querySelectorAll("[data-stat]");

if (statRows.length && "IntersectionObserver" in window) {
  const statObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
        statObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.4 });

  statRows.forEach((row) => statObserver.observe(row));
} else {
  statRows.forEach((row) => row.classList.add("is-visible"));
}

document.querySelectorAll(".type-text").forEach((node) => {
  const fullHtml = node.innerHTML;
  const plain = node.textContent;
  node.textContent = "";
  let i = 0;
  const speed = 32;
  const tick = () => {
    i += 1;
    node.textContent = plain.slice(0, i);
    if (i < plain.length) {
      window.setTimeout(tick, speed);
    } else {
      node.innerHTML = fullHtml;
    }
  };
  window.setTimeout(tick, 400);
});

function createMessage(text, role, isTyping = false, meta = {}) {
  const article = document.createElement("article");
  article.className = `message ${role}-message${isTyping ? " typing" : ""}`;

  if (role === "assistant") {
    const avatar = document.createElement("img");
    avatar.src = "aurora-sprite.svg";
    avatar.alt = "";
    avatar.width = 40;
    avatar.height = 40;
    article.appendChild(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  if (isTyping) {
    const dots = document.createElement("span");
    dots.className = "typing-dots";
    dots.setAttribute("aria-label", "Aurora is thinking");
    dots.innerHTML = "<span></span><span></span><span></span>";
    bubble.appendChild(dots);
  } else {
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    bubble.appendChild(paragraph);

    if (role === "assistant") {
      const citations = Array.isArray(meta.citations) ? meta.citations : [];
      if (citations.length) {
        bubble.appendChild(createCitationList(citations));
      }
      if (meta.trace) {
        bubble.appendChild(createTraceLine(meta.trace));
      }
    }
  }

  article.appendChild(bubble);
  return article;
}

function createCitationList(citations) {
  const list = document.createElement("ol");
  list.className = "citation-list";
  citations.slice(0, 4).forEach((citation) => {
    const item = document.createElement("li");
    const title = citation.title || citation.doc_id || citation.chunk_id || "Source";
    const detail = citation.citation || citation.chunk_id || citation.doc_id || "";
    item.textContent = detail ? `${title}: ${detail}` : title;
    list.appendChild(item);
  });
  return list;
}

function createTraceLine(trace) {
  const line = document.createElement("p");
  line.className = "trace-line";
  const mode = trace.execution_mode || trace.retrieval_mode || "unknown";
  const runtime = trace.runtime || "unknown";
  line.textContent = `trace ${mode} | ${runtime}`;
  return line;
}

function scrollMessages() {
  if (messageList) {
    messageList.scrollTop = messageList.scrollHeight;
  }
}

async function requestAnswer(text) {
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

async function requestOcr(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetchWithTimeout(`${API_BASE}/documents/ocr`, {
    method: "POST",
    body: formData
  });
  await ensureOk(response);
  return response.json();
}

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

async function sendMessage(text) {
  if (!text.trim() || !messageList) {
    return;
  }

  messageList.appendChild(createMessage(text.trim(), "user"));
  scrollMessages();

  const typing = createMessage("", "assistant", true);
  messageList.appendChild(typing);
  scrollMessages();

  try {
    const payload = await requestAnswer(text.trim());
    typing.remove();
    const answer = payload.answer || "Backend returned an empty answer.";
    messageList.appendChild(createMessage(answer, "assistant", false, {
      citations: payload.citations,
      trace: payload.retrieval_trace
    }));
    scrollMessages();
  } catch (error) {
    typing.remove();
    const message = error.message === "request.timeout"
      ? "The API request timed out. Please try again with a shorter question."
      : "Backend is unavailable. Please try again after the API service is running.";
    messageList.appendChild(createMessage(
      message,
      "assistant",
      false,
      { trace: { runtime: "offline", execution_mode: "request_failed" } }
    ));
    scrollMessages();
    console.error(error);
  }
}

function requestHandoff() {
  if (!messageList) {
    return;
  }

  messageList.appendChild(createMessage("Please connect me with a human attorney.", "user"));
  scrollMessages();

  const typing = createMessage("", "assistant", true);
  messageList.appendChild(typing);
  scrollMessages();

  window.setTimeout(() => {
    typing.remove();
    messageList.appendChild(createMessage(
      "This handoff is demo only. In production, this action must call a reviewed attorney workflow before any human follow-up is promised.",
      "assistant"
    ));
    scrollMessages();
  }, 650);
}

function renderOcrPreview(payload) {
  if (!messageList) {
    return;
  }
  const article = document.createElement("article");
  article.className = "message assistant-message";

  const avatar = document.createElement("img");
  avatar.src = "aurora-sprite.svg";
  avatar.alt = "";
  avatar.width = 40;
  avatar.height = 40;
  article.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const title = document.createElement("p");
  title.textContent = "OCR extracted text preview";
  bubble.appendChild(title);

  const preview = document.createElement("pre");
  preview.className = "ocr-preview";
  preview.textContent = payload.text || "No text was extracted.";
  bubble.appendChild(preview);

  article.appendChild(bubble);
  messageList.appendChild(article);
  scrollMessages();
}

async function submitOcrUpload(event) {
  event.preventDefault();
  if (!ocrFile || !ocrFile.files || !ocrFile.files[0] || !messageList) {
    return;
  }
  const file = ocrFile.files[0];
  messageList.appendChild(createMessage(`Upload OCR file: ${file.name}`, "user"));
  const typing = createMessage("", "assistant", true);
  messageList.appendChild(typing);
  scrollMessages();
  try {
    const payload = await requestOcr(file);
    typing.remove();
    renderOcrPreview(payload);
  } catch (error) {
    typing.remove();
    const message = error.message === "request.timeout"
      ? "The API request timed out while processing OCR."
      : "OCR is unavailable or rejected this file.";
    messageList.appendChild(createMessage(message, "assistant"));
    scrollMessages();
    console.error(error);
  } finally {
    ocrForm.reset();
  }
}

if (chatForm && chatInput) {
  chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(chatInput.value);
    chatInput.value = "";
    chatInput.focus();
  });
}

promptButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const prompt = button.getAttribute("data-prompt") || "";
    if (chatInput) {
      chatInput.value = prompt;
      chatInput.focus();
    }
    sendMessage(prompt);
    if (chatInput) {
      chatInput.value = "";
    }
  });
});

handoffButtons.forEach((button) => {
  button.addEventListener("click", requestHandoff);
});

if (ocrForm) {
  ocrForm.addEventListener("submit", submitOcrUpload);
}
