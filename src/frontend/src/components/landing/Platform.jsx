import Reveal from "../Reveal.jsx";

const CARDS = [
  {
    delay: 0,
    fill: "var(--brand)",
    badge: "Intake",
    title: "Fact pattern capture",
    body: "Gather names, dates, filings, claims, deadlines, and risk signals without burying the client in a form.",
    icon: (
      <svg viewBox="0 0 12 12" fill="var(--brand)">
        <rect x="5" y="1" width="2" height="6" />
        <rect x="3" y="5" width="2" height="2" />
        <rect x="7" y="5" width="2" height="2" />
        <rect x="1" y="9" width="10" height="2" />
        <rect x="1" y="7" width="2" height="2" />
        <rect x="9" y="7" width="2" height="2" />
      </svg>
    )
  },
  {
    delay: 1,
    badge: "Research",
    title: "Cited answer drafts",
    body: "Convert vague questions into scoped legal issues, then organize authorities, caveats, and unresolved facts.",
    icon: (
      <svg viewBox="0 0 12 12" fill="var(--accent-yellow)">
        <rect x="2" y="2" width="6" height="6" />
        <rect x="3.5" y="3.5" width="3" height="3" fill="var(--panel-soft)" />
        <rect x="7" y="7" width="2" height="2" />
        <rect x="9" y="9" width="2" height="2" />
      </svg>
    )
  },
  {
    delay: 2,
    badge: "Review",
    title: "Human approval lane",
    body: "Escalate uncertain answers, privilege-sensitive content, and jurisdiction gaps before advice reaches a client.",
    icon: (
      <svg viewBox="0 0 12 12" fill="var(--accent-purple)">
        <rect x="2" y="1" width="8" height="7" />
        <rect x="3" y="8" width="6" height="1" />
        <rect x="4" y="9" width="4" height="1" />
        <rect x="5" y="10" width="2" height="1" />
        <rect x="4" y="5" width="1" height="2" fill="var(--panel-soft)" />
        <rect x="5" y="6" width="1" height="1" fill="var(--panel-soft)" />
        <rect x="6" y="3" width="1" height="4" fill="var(--panel-soft)" />
        <rect x="7" y="2" width="1" height="1" fill="var(--panel-soft)" />
      </svg>
    )
  }
];

export default function Platform() {
  return (
    <section className="section" id="platform">
      <div className="container">
        <Reveal className="section-header">
          <p className="eyebrow">Platform</p>
          <h2>Legal work with a clean chain of thought.</h2>
          <p className="lead">
            Aurora keeps the conversation close to the matter record: facts, jurisdiction,
            issue, authority, and recommended action.
          </p>
        </Reveal>
        <div className="card-grid three">
          {CARDS.map((card) => (
            <Reveal as="article" className="card" delay={card.delay} key={card.title}>
              <span className="card-icon" aria-hidden="true">
                {card.icon}
              </span>
              <span className="badge">{card.badge}</span>
              <h3>{card.title}</h3>
              <p>{card.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
