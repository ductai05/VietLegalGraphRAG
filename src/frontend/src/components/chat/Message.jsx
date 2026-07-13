// One conversation message. Mirrors createMessage / createCitationList /
// createTraceLine / renderOcrPreview from the original app.js.

function CitationList({ citations }) {
  return (
    <ol className="citation-list">
      {citations.slice(0, 4).map((citation, index) => {
        const title = citation.title || citation.doc_id || citation.chunk_id || "Source";
        const detail = citation.citation || citation.chunk_id || citation.doc_id || "";
        return <li key={index}>{detail ? `${title}: ${detail}` : title}</li>;
      })}
    </ol>
  );
}

function TraceLine({ trace }) {
  const mode = trace.execution_mode || trace.retrieval_mode || "unknown";
  const runtime = trace.runtime || "unknown";
  return <p className="trace-line">{`trace ${mode} | ${runtime}`}</p>;
}

export default function Message({ msg }) {
  const isAssistant = msg.role === "assistant";
  const citations = Array.isArray(msg.citations) ? msg.citations : [];

  return (
    <article className={`message ${msg.role}-message${msg.typing ? " typing" : ""}`}>
      {isAssistant && <img src="/aurora-sprite.svg" alt="" width="40" height="40" />}
      <div className="bubble">
        {msg.typing ? (
          <span className="typing-dots" aria-label="Aurora is thinking">
            <span></span>
            <span></span>
            <span></span>
          </span>
        ) : msg.kind === "ocr" ? (
          <>
            <p>OCR extracted text preview</p>
            <pre className="ocr-preview">{msg.ocrText || "No text was extracted."}</pre>
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
