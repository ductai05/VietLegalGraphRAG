import { Link } from "react-router-dom";
import Reveal from "../Reveal.jsx";
import { useTypewriter } from "../../hooks/useTypewriter.js";

export default function Hero() {
  // Original markup: "A wild <strong>LEGAL QUESTION</strong> appeared!"
  // The typewriter types the plain text, then the emphasis is restored.
  const typed = useTypewriter("A wild LEGAL QUESTION appeared!");
  const done = typed.length >= "A wild LEGAL QUESTION appeared!".length;

  return (
    <section className="hero section">
      <div className="container battle-grid">
        <Reveal className="battle-copy">
          <p className="eyebrow">» Legal AI Encounter</p>
          <h1>Aurora</h1>
          <p className="lead">
            A pixel-powered legal companion that turns client questions, case facts, and
            document fragments into structured next steps — no grinding required.
          </p>
          <div className="hero-actions">
            <Link className="button button-brand" to="/chat">Start a Conversation</Link>
            <a className="button button-secondary" href="#engine">See the Engine</a>
          </div>
          <p className="engine-chip">
            Powered by <strong>VietLegalGraphRAG</strong>
          </p>
        </Reveal>
        <Reveal className="battle-arena" delay={1} aria-hidden="true">
          <div className="dialogue-box">
            {done ? (
              <p className="type-text">
                A wild <strong>LEGAL QUESTION</strong> appeared!
              </p>
            ) : (
              <p className="type-text">{typed}</p>
            )}
          </div>
          <div className="arena-row">
            <div className="combatant combatant-player">
              <span className="name-tag">
                AURORA <span className="lv">Lv.99</span>
              </span>
              <img
                className="sprite sprite-float"
                src="/aurora-sprite.svg"
                width="128"
                height="128"
                alt="Aurora, your legal AI ally"
              />
              <div className="platform"></div>
            </div>
            <div className="combatant combatant-foe">
              <span className="name-tag">CASE FILE</span>
              <img
                className="sprite sprite-float delay"
                src="/case-sprite.svg"
                width="104"
                height="104"
                alt="A wild legal case appears"
              />
              <div className="platform platform-foe"></div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
