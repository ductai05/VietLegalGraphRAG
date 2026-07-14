import { useEffect, useRef } from "react";
import Message from "./Message.jsx";

export default function MessageList({ messages }) {
  const listRef = useRef(null);

  // Auto-scroll to the newest message (scrollMessages in the original).
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="message-list" id="message-list" aria-live="polite" ref={listRef}>
      {messages.map((msg) => (
        <Message key={msg.id} msg={msg} />
      ))}
    </div>
  );
}
