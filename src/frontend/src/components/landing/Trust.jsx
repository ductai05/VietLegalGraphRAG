import Reveal from "../Reveal.jsx";
import { useReveal } from "../../hooks/useReveal.js";

const STATS = [
  { fill: "100%", label: "UPTIME", metric: "24/7", caption: "Matter intake availability, day or night." },
  { fill: "100%", label: "REVIEW", metric: "100%", caption: "Every answer is attorney review compatible." },
  { fill: "0%", label: "LEAKAGE", metric: "0", caption: "Zero decorative data leaks — empty bar is the goal.", danger: true }
];

// Stat rows animate their fill bar on scroll via their own observer
// (threshold 0.4, matching the original statObserver in app.js).
function StatRow({ fill, label, metric, caption, danger }) {
  const [ref, visible] = useReveal(0.4);
  return (
    <div
      ref={ref}
      className={`stat-row${visible ? " is-visible" : ""}`}
      data-stat
      style={{ "--fill": fill }}
    >
      <div className="stat-row-head">
        <span>{label}</span>
        <span className="metric">{metric}</span>
      </div>
      <div className="stat-track">
        <div className={`stat-fill${danger ? " is-danger" : ""}`}></div>
      </div>
      <p className="stat-caption">{caption}</p>
    </div>
  );
}

export default function Trust() {
  return (
    <section className="section" id="trust">
      <div className="container">
        <Reveal className="section-header">
          <p className="eyebrow">Trust</p>
          <h2>Status screen: designed for legal boundaries.</h2>
          <p className="lead">
            Aurora is built around cautious language, source awareness, human review, and clear
            disclaimers where professional judgment belongs.
          </p>
        </Reveal>
        <Reveal className="trust-band" delay={1}>
          {STATS.map((stat) => (
            <StatRow key={stat.label} {...stat} />
          ))}
        </Reveal>
      </div>
    </section>
  );
}
