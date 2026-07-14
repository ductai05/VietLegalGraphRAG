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

export default function Message({ msg }) {
  const isAssistant = msg.role === "assistant";
  const citations = Array.isArray(msg.citations) ? msg.citations : [];

  return (
    <article className={`message ${msg.role}-message${msg.typing ? " typing" : ""}`}>
      {isAssistant && <img src="/aurora-sprite.svg" alt="" width="40" height="40" />}
      <div className="bubble">
        {msg.typing ? (
          <span className="typing-dots" aria-label="Aurora đang xử lý">
            <span></span>
            <span></span>
            <span></span>
          </span>
        ) : msg.kind === "ocr" ? (
          <>
            <p>Xem trước văn bản trích xuất OCR</p>
            <pre className="ocr-preview">{msg.ocrText || "Không trích xuất được văn bản nào."}</pre>
          </>
        ) : (
          <>
            <p>{msg.text}</p>
            {isAssistant && citations.length > 0 && <CitationList citations={citations} />}
            {isAssistant && msg.trace && <TraceLine trace={msg.trace} />}
          </>
        )}
      </div>
    </article>
  );
}
