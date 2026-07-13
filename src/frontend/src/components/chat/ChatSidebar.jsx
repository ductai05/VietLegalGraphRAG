import { useState } from "react";
import { Link } from "react-router-dom";

const MATTERS = ["Civil intake", "Contract review", "Employment issue", "Deadline check"];

const STATUS = [
  { term: "Jurisdiction", value: "Unconfirmed" },
  { term: "Urgency", value: "Screening" },
  { term: "Review", value: "Attorney required" }
];

export default function ChatSidebar({ onHandoff }) {
  const [active, setActive] = useState(MATTERS[0]);

  return (
    <aside className="chat-sidebar" aria-label="Matter context">
      <Link className="brand" to="/" aria-label="Aurora home">
        <img src="/aurora-sprite.svg" alt="" width="40" height="40" />
        <span>Aurora</span>
      </Link>
      <div>
        <p className="sidebar-title">Matters</p>
        <nav className="matter-nav" aria-label="Conversation shortcuts">
          {MATTERS.map((matter) => (
            <button
              key={matter}
              type="button"
              className={active === matter ? "active" : undefined}
              onClick={() => setActive(matter)}
            >
              {matter}
            </button>
          ))}
        </nav>
      </div>
      <div className="side-panel">
        <p className="eyebrow">Status Screen</p>
        <dl>
          {STATUS.map((row) => (
            <div key={row.term}>
              <dt>{row.term}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        <div className="side-support">
          <p>Stuck, or need a real human? Aurora can mark this matter for a demo handoff review.</p>
          <button
            className="button button-secondary button-small"
            type="button"
            data-handoff
            onClick={onHandoff}
          >
            Request Handoff
          </button>
        </div>
      </div>
    </aside>
  );
}
