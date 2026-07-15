// One conversation message. Mirrors createMessage / createCitationList /
// createTraceLine / renderOcrPreview from the original app.js.

function CitationList({ citations }) {
  return (
    <ol className="citation-list">
      {citations.slice(0, 4).map((citation, index) => {
        const title = citation.title || citation.doc_id || citation.chunk_id || "Nguồn";
        const detail = citation.citation || citation.chunk_id || citation.doc_id || "";
        return <li key={index}>{detail ? `${title}: ${detail}` : title}</li>;
      })}
    </ol>
  );
}

function TraceLine({ trace }) {
  const mode = trace.execution_mode || trace.retrieval_mode || "không xác định";
  const runtime = trace.runtime || "không xác định";
  return <p className="trace-line">{`vết xử lý ${mode} | ${runtime}`}</p>;
}

function parseStreamingText(rawText) {
  const thinkStart = rawText.indexOf("<think>");
  const thinkEnd = rawText.indexOf("</think>");

  if (thinkStart !== -1) {
    if (thinkEnd !== -1) {
      return {
        thinkingText: rawText.substring(thinkStart + 7, thinkEnd).trim(),
        answerText: rawText.substring(thinkEnd + 8).trim(),
        isThinking: false
      };
    } else {
      return {
        thinkingText: rawText.substring(thinkStart + 7).trim(),
        answerText: "",
        isThinking: true
      };
    }
  }

  return {
    thinkingText: "",
    answerText: rawText.trim(),
    isThinking: false
  };
}

export default function Message({ msg }) {
  const isAssistant = msg.role === "assistant";
  const citations = Array.isArray(msg.citations) ? msg.citations : [];
  const { thinkingText, answerText, isThinking } = parseStreamingText(msg.text || "");

  return (
    <article className={`message ${msg.role}-message${msg.typing ? " typing" : ""}`}>
      {isAssistant && <img src="/aurora-sprite.svg" alt="" width="40" height="40" />}
      <div className="bubble">
        {msg.typing || (isAssistant && !thinkingText && !answerText) ? (
          <>
            <span className="typing-dots" aria-label="Aurora đang xử lý">
              <span></span>
              <span></span>
              <span></span>
            </span>
            {isAssistant && citations.length > 0 && <CitationList citations={citations} />}
          </>
        ) : msg.kind === "ocr" ? (
          <>
            <p>Xem trước văn bản trích xuất OCR</p>
            <pre className="ocr-preview">{msg.ocrText || "Không trích xuất được văn bản nào."}</pre>
          </>
        ) : (
          <>
            {thinkingText && (
              <details className="thinking-accordion" open={isThinking}>
                <summary className="thinking-header">
                  <span className={`thinking-status-dot${isThinking ? " pulsing" : ""}`}></span>
                  <span className="thinking-title">
                    {isThinking ? "Đang phân tích lập luận..." : "Quá trình lập luận thực tế"}
                  </span>
                </summary>
                <div className="thinking-content">
                  {thinkingText}
                </div>
              </details>
            )}
            {answerText && <p>{answerText}</p>}
            {isAssistant && citations.length > 0 && <CitationList citations={citations} />}
            {isAssistant && msg.trace && <TraceLine trace={msg.trace} />}
          </>
        )}
      </div>
    </article>
  );
}
