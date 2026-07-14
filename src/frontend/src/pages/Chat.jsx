import { useCallback, useEffect, useRef, useState } from "react";
import ChatSidebar from "../components/chat/ChatSidebar.jsx";
import Conversation from "../components/chat/Conversation.jsx";
import { requestAnswer, requestOcr } from "../lib/api.js";

const SEED_MESSAGES = [
  {
    id: "seed-1",
    role: "assistant",
    text: "Tôi có thể giúp bạn trình bày vấn đề pháp lý một cách rõ ràng để luật sư xem xét. Chuyện gì đã xảy ra, xảy ra ở đâu, và bạn đang lo ngại về thời hạn nào?"
  },
  {
    id: "seed-2",
    role: "user",
    text: "Tôi vừa nhận được thông báo chấm dứt hợp đồng và cần biết bước tiếp theo phải làm gì."
  },
  {
    id: "seed-3",
    role: "assistant",
    text: "Vui lòng cung cấp điều khoản luật áp dụng, ngày ra thông báo, ngày chấm dứt hợp đồng có hiệu lực, và các điều khoản về thời hạn khắc phục (nếu có). Tôi sẽ tách riêng các sự kiện đã xác nhận và các câu hỏi cần luật sư giải đáp."
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
          text: payload.answer || "Máy chủ trả về câu trả lời trống.",
          citations: payload.citations,
          trace: payload.retrieval_trace
        });
      } catch (error) {
        removeMessage(typingId);
        const message =
          error.message === "request.timeout"
            ? "Yêu cầu đã hết thời gian chờ. Vui lòng thử lại với câu hỏi ngắn hơn."
            : "Hệ thống hiện không khả dụng. Vui lòng thử lại sau khi dịch vụ API hoạt động trở lại.";
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
    addMessage({ role: "user", text: "Vui lòng kết nối tôi với một luật sư thật." });
    const typingId = addMessage({ role: "assistant", typing: true });

    window.setTimeout(() => {
      removeMessage(typingId);
      addMessage({
        role: "assistant",
        text:
          "Đây chỉ là tính năng demo cho việc chuyển tiếp. Trong môi trường thực tế, thao tác này cần gọi đến quy trình xét duyệt của luật sư trước khi cam kết bất kỳ hỗ trợ trực tiếp nào từ con người."
      });
    }, 650);
  }, [addMessage, removeMessage]);

  const submitOcr = useCallback(
    async (file) => {
      addMessage({ role: "user", text: `Tải lên tệp OCR: ${file.name}` });
      const typingId = addMessage({ role: "assistant", typing: true });

      try {
        const payload = await requestOcr(file);
        removeMessage(typingId);
        addMessage({ role: "assistant", kind: "ocr", ocrText: payload.text });
      } catch (error) {
        removeMessage(typingId);
        const message =
          error.message === "request.timeout"
            ? "Yêu cầu xử lý OCR đã hết thời gian chờ."
            : "Chức năng OCR hiện không khả dụng hoặc đã từ chối tệp này.";
        addMessage({ role: "assistant", text: message });
        console.error(error);
      }
    },
    [addMessage, removeMessage]
  );

  return (
    <main className="chat-shell" aria-label="Trợ lý pháp lý Aurora">
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
