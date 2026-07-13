import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div>
          <Link className="brand brand-inverted" to="/" aria-label="Aurora home">
            <img src="/aurora-sprite.svg" alt="" width="40" height="40" />
            <span>Aurora</span>
          </Link>
          <p>Legal chatbot system built on VietLegalGraphRAG for structured intake and research.</p>
        </div>
        <Link className="button button-light" to="/chat">Open Chat</Link>
      </div>
    </footer>
  );
}
