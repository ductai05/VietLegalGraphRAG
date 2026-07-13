import Reveal from "../Reveal.jsx";

// SVG animations use SMIL (<animate>, <animateMotion>) copied verbatim from the
// original markup; embedded as raw HTML to preserve every attribute exactly.
const VECTOR_SVG = `
<svg class="rag-visual" viewBox="0 0 220 150" role="img" aria-label="Animated diagram of dense vector search finding nearest neighbors in embedding space">
  <circle cx="30" cy="40" r="3" fill="var(--body-subtle)" opacity="0.5"/>
  <circle cx="55" cy="95" r="3" fill="var(--body-subtle)" opacity="0.5"/>
  <circle cx="100" cy="115" r="3" fill="var(--body-subtle)" opacity="0.5"/>
  <circle cx="170" cy="35" r="3" fill="var(--body-subtle)" opacity="0.5"/>
  <circle cx="190" cy="70" r="3" fill="var(--body-subtle)" opacity="0.5"/>
  <circle cx="45" cy="125" r="3" fill="var(--body-subtle)" opacity="0.5"/>
  <circle cx="165" cy="120" r="3" fill="var(--body-subtle)" opacity="0.5"/>
  <line x1="108" y1="74" x2="80" y2="60" stroke="var(--brand)" stroke-width="2" stroke-dasharray="6 4">
    <animate attributeName="stroke-dashoffset" values="20;0" dur="1s" begin="0s" repeatCount="indefinite"/>
  </line>
  <line x1="108" y1="74" x2="130" y2="50" stroke="var(--brand)" stroke-width="2" stroke-dasharray="6 4">
    <animate attributeName="stroke-dashoffset" values="20;0" dur="1s" begin="0.3s" repeatCount="indefinite"/>
  </line>
  <line x1="108" y1="74" x2="150" y2="90" stroke="var(--brand)" stroke-width="2" stroke-dasharray="6 4">
    <animate attributeName="stroke-dashoffset" values="20;0" dur="1s" begin="0.6s" repeatCount="indefinite"/>
  </line>
  <circle cx="80" cy="60" r="3.5" fill="var(--body-subtle)">
    <animate attributeName="fill" values="var(--body-subtle);var(--brand);var(--body-subtle)" keyTimes="0;0.3;1" dur="2.2s" begin="0s" repeatCount="indefinite"/>
  </circle>
  <circle cx="130" cy="50" r="3.5" fill="var(--body-subtle)">
    <animate attributeName="fill" values="var(--body-subtle);var(--brand);var(--body-subtle)" keyTimes="0;0.3;1" dur="2.2s" begin="0.3s" repeatCount="indefinite"/>
  </circle>
  <circle cx="150" cy="90" r="3.5" fill="var(--body-subtle)">
    <animate attributeName="fill" values="var(--body-subtle);var(--brand);var(--body-subtle)" keyTimes="0;0.3;1" dur="2.2s" begin="0.6s" repeatCount="indefinite"/>
  </circle>
  <circle cx="108" cy="74" r="18" fill="none" stroke="var(--brand)" stroke-width="2" opacity="0.6">
    <animate attributeName="r" values="7;30" dur="2.2s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.6;0" dur="2.2s" repeatCount="indefinite"/>
  </circle>
  <circle cx="108" cy="74" r="7" fill="var(--brand)"/>
</svg>`;

const KEYWORD_SVG = `
<svg class="rag-visual" viewBox="0 0 220 150" role="img" aria-label="Animated diagram of a scan line sweeping across text and highlighting matched keywords">
  <rect x="10" y="20" width="30" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="46" y="20" width="40" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="92" y="20" width="24" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="122" y="20" width="50" height="10" rx="2" fill="var(--accent-yellow)" opacity="0.35">
    <animate attributeName="opacity" values="0.35;1;0.35" keyTimes="0;0.5;1" dur="3s" begin="0.3s" repeatCount="indefinite"/>
  </rect>
  <rect x="10" y="45" width="50" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="66" y="45" width="20" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="92" y="45" width="60" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="10" y="70" width="26" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="42" y="70" width="44" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="92" y="70" width="20" height="10" rx="2" fill="var(--accent-yellow)" opacity="0.35">
    <animate attributeName="opacity" values="0.35;1;0.35" keyTimes="0;0.5;1" dur="3s" begin="1.2s" repeatCount="indefinite"/>
  </rect>
  <rect x="118" y="70" width="36" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="10" y="95" width="40" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="56" y="95" width="54" height="10" rx="2" fill="var(--accent-yellow)" opacity="0.35">
    <animate attributeName="opacity" values="0.35;1;0.35" keyTimes="0;0.5;1" dur="3s" begin="1.7s" repeatCount="indefinite"/>
  </rect>
  <rect x="116" y="95" width="34" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="10" y="120" width="60" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="76" y="120" width="20" height="10" rx="2" fill="var(--body-subtle)" opacity="0.35"/>
  <rect x="102" y="120" width="48" height="10" rx="2" fill="var(--accent-yellow)" opacity="0.35">
    <animate attributeName="opacity" values="0.35;1;0.35" keyTimes="0;0.5;1" dur="3s" begin="2.1s" repeatCount="indefinite"/>
  </rect>
  <rect x="0" y="-10" width="220" height="6" fill="var(--accent-yellow)" opacity="0.4">
    <animate attributeName="y" values="-10;150" dur="3s" repeatCount="indefinite"/>
  </rect>
</svg>`;

const GRAPH_SVG = `
<svg class="rag-visual" viewBox="0 0 220 150" role="img" aria-label="Animated diagram of a knowledge graph with pulses traveling between connected entities">
  <path id="edge1" d="M100 80 L40 40" stroke="var(--panel-light)" stroke-width="2" opacity="0.7"/>
  <path id="edge2" d="M100 80 L110 25" stroke="var(--panel-light)" stroke-width="2" opacity="0.7"/>
  <path id="edge3" d="M100 80 L180 45" stroke="var(--panel-light)" stroke-width="2" opacity="0.7"/>
  <path id="edge4" d="M100 80 L60 110" stroke="var(--panel-light)" stroke-width="2" opacity="0.7"/>
  <path id="edge5" d="M100 80 L140 120" stroke="var(--panel-light)" stroke-width="2" opacity="0.7"/>
  <path d="M40 40 L110 25" stroke="var(--panel-light)" stroke-width="1.5" opacity="0.4"/>
  <path d="M180 45 L140 120" stroke="var(--panel-light)" stroke-width="1.5" opacity="0.4"/>
  <circle cx="40" cy="40" r="6" fill="var(--accent-purple)">
    <animate attributeName="r" values="6;7.5;6" dur="2.4s" begin="0s" repeatCount="indefinite"/>
  </circle>
  <circle cx="110" cy="25" r="6" fill="var(--accent-purple)">
    <animate attributeName="r" values="6;7.5;6" dur="2.4s" begin="0.2s" repeatCount="indefinite"/>
  </circle>
  <circle cx="180" cy="45" r="6" fill="var(--accent-purple)">
    <animate attributeName="r" values="6;7.5;6" dur="2.4s" begin="0.4s" repeatCount="indefinite"/>
  </circle>
  <circle cx="60" cy="110" r="6" fill="var(--accent-purple)">
    <animate attributeName="r" values="6;7.5;6" dur="2.4s" begin="0.6s" repeatCount="indefinite"/>
  </circle>
  <circle cx="140" cy="120" r="6" fill="var(--accent-purple)">
    <animate attributeName="r" values="6;7.5;6" dur="2.4s" begin="0.8s" repeatCount="indefinite"/>
  </circle>
  <circle cx="100" cy="80" r="8" fill="var(--brand)"/>
  <circle r="4" fill="var(--brand-strong)">
    <animateMotion dur="1.8s" begin="0s" repeatCount="indefinite">
      <mpath href="#edge1"/>
    </animateMotion>
  </circle>
  <circle r="4" fill="var(--brand-strong)">
    <animateMotion dur="1.8s" begin="0.6s" repeatCount="indefinite">
      <mpath href="#edge3"/>
    </animateMotion>
  </circle>
  <circle r="4" fill="var(--brand-strong)">
    <animateMotion dur="1.8s" begin="1.2s" repeatCount="indefinite">
      <mpath href="#edge5"/>
    </animateMotion>
  </circle>
</svg>`;

const MOVES = [
  {
    delay: 0,
    tagClass: "move-tag--vector",
    tag: "Move 1",
    title: "Dense Vector Search",
    svg: VECTOR_SVG,
    body: "Query and passages meet in embedding space — Aurora pulls the semantically closest chunks, not just the ones that share words."
  },
  {
    delay: 1,
    tagClass: "move-tag--keyword",
    tag: "Move 2",
    title: "Keyword Matching",
    svg: KEYWORD_SVG,
    body: "Exact terms still count. Statute numbers, defined terms, and dates get matched literally so nothing precise slips through."
  },
  {
    delay: 2,
    tagClass: "move-tag--graph",
    tag: "Move 3",
    title: "LightRAG Graph Traversal",
    svg: GRAPH_SVG,
    body: "Entities and relationships form a case graph — parties, clauses, dates — so Aurora can hop context instead of guessing it."
  }
];

export default function Engine() {
  return (
    <section className="section" id="engine">
      <div className="container">
        <Reveal className="section-header">
          <p className="eyebrow">The Engine</p>
          <h2>VietLegalGraphRAG — three moves, one answer.</h2>
          <p className="lead">
            Every question triggers three retrieval moves at once. Aurora blends their results
            before a single word is drafted.
          </p>
        </Reveal>
        <div className="rag-grid">
          {MOVES.map((move) => (
            <Reveal as="article" className="rag-card" delay={move.delay} key={move.tag}>
              <span className={`move-tag ${move.tagClass}`}>{move.tag}</span>
              <h3>{move.title}</h3>
              <div dangerouslySetInnerHTML={{ __html: move.svg }} />
              <p>{move.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
