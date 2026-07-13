import { useCallback, useEffect, useRef, useState } from "react";
import ChatSidebar from "../components/chat/ChatSidebar.jsx";
import Conversation from "../components/chat/Conversation.jsx";
import { requestAnswer, requestOcr } from "../lib/api.js";

const SEED_MESSAGES = [
  {
    id: "seed-1",
    role: "assistant",
    text: "I can help structure your legal question for review. What happened, where did it happen, and what deadline are you worried about?"
  },
  {
    id: "seed-2",
    role: "user",
    text: "I received a contract termination notice and need to know what to do next."
  },
  {
    id: "seed-3",
    role: "assistant",
    text: "Please share the governing law clause, notice date, effective termination date, and any cure period language. I will separate confirmed facts from questions for counsel."
  }
];

export default function Chat() {
  const [messages, setMessages] = useState(SEED_MESSAGES);
  const idCounter = useRef(0);

  useEffect(() => {
    document.body.classList.add("chat-body");
    return () => document.body.classList.remove("chat-body");
  }, []);

  const addMessage = useCallback((message) => {
    const id = message.id ?? `msg-${(idCounter.current += 1)}`;
    setMessages((prev) => [...prev, { ...message, id }]);
    return id;
  }, []);

  const removeMessage = useCallback((id) => {
    setMessages((prev) => prev.filter((msg) => msg.id !== id));
  }, []);

  const sendMessage = useCallback(
    async (rawText) => {
      const text = (rawText || "").trim();
      if (!text) {
        return;
      }

      addMessage({ role: "user", text });
      const typingId = addMessage({ role: "assistant", typing: true });

      try {
        const payload = await requestAnswer(text);
        removeMessage(typingId);
        addMessage({
          role: "assistant",
          text: payload.answer || "Backend returned an empty answer.",
          citations: payload.citations,
          trace: payload.retrieval_trace
        });
      } catch (error) {
        removeMessage(typingId);
        const message =
          error.message === "request.timeout"
            ? "The API request timed out. Please try again with a shorter question."
            : "Backend is unavailable. Please try again after the API service is running.";
        addMessage({
          role: "assistant",
          text: message,
          trace: { runtime: "offline", execution_mode: "request_failed" }
        });
        console.error(error);
      }
    },
    [addMessage, removeMessage]
  );

  const requestHandoff = useCallback(() => {
    addMessage({ role: "user", text: "Please connect me with a human attorney." });
    const typingId = addMessage({ role: "assistant", typing: true });

    window.setTimeout(() => {
      removeMessage(typingId);
      addMessage({
        role: "assistant",
        text:
          "This handoff is demo only. In production, this action must call a reviewed attorney workflow before any human follow-up is promised."
      });
    }, 650);
  }, [addMessage, removeMessage]);

  const submitOcr = useCallback(
    async (file) => {
      addMessage({ role: "user", text: `Upload OCR file: ${file.name}` });
      const typingId = addMessage({ role: "assistant", typing: true });

      try {
        const payload = await requestOcr(file);
        removeMessage(typingId);
        addMessage({ role: "assistant", kind: "ocr", ocrText: payload.text });
      } catch (error) {
        removeMessage(typingId);
        const message =
          error.message === "request.timeout"
            ? "The API request timed out while processing OCR."
            : "OCR is unavailable or rejected this file.";
        addMessage({ role: "assistant", text: message });
        console.error(error);
      }
    },
    [addMessage, removeMessage]
  );

  return (
    <main className="chat-shell" aria-label="Aurora legal chatbot">
      <ChatSidebar onHandoff={requestHandoff} />
      <Conversation
        messages={messages}
        onSend={sendMessage}
        onPrompt={sendMessage}
        onHandoff={requestHandoff}
        onOcr={submitOcr}
      />
    </main>
  );
}
