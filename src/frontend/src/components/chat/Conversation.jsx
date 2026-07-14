import { Link } from "react-router-dom";
import MessageList from "./MessageList.jsx";
import PromptRow from "./PromptRow.jsx";
import OcrForm from "./OcrForm.jsx";
import Composer from "./Composer.jsx";

export default function Conversation({ messages, onSend, onPrompt, onHandoff, onOcr }) {
  return (
    <section className="conversation" aria-label="Cuộc hội thoại">
      <header className="conversation-header">
        <div className="agent-title">
          <img src="/aurora-sprite.svg" alt="" width="48" height="48" />
          <div>
            <h1>
              Aurora <span style={{ color: "var(--accent-yellow)" }}>Lv.99</span>
            </h1>
            <p>Trợ lý tiếp nhận vụ việc pháp lý · VietLegalGraphRAG</p>
          </div>
        </div>
        <Link className="button button-tertiary button-small" to="/">Trang chủ</Link>
      </header>

      <MessageList messages={messages} />

      <PromptRow onPrompt={onPrompt} onHandoff={onHandoff} />

      <OcrForm onSubmit={onOcr} />

      <Composer onSend={onSend} />
    </section>
  );
}
