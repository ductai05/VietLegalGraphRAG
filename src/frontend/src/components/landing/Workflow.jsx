import Reveal from "../Reveal.jsx";

const STEPS = [
  { n: "01", title: "Qualify", body: "Identify jurisdiction, party role, timeline, and urgency." },
  { n: "02", title: "Analyze", body: "Separate facts from assumptions and surface likely legal issues." },
  { n: "03", title: "Prepare", body: "Create a concise summary, document checklist, and attorney handoff." }
];

export default function Workflow() {
  return (
    <section className="section" id="workflow">
      <div className="container split">
        <Reveal className="section-header">
          <p className="eyebrow">Workflow</p>
          <h2>From first message to matter-ready summary.</h2>
          <p className="lead">
            The assistant asks only for facts that change the legal analysis, then packages the
            conversation for counsel.
          </p>
        </Reveal>
        <Reveal className="timeline" delay={1} aria-label="Aurora workflow">
          {STEPS.map((step) => (
            <div className="timeline-item" key={step.n}>
              <span>{step.n}</span>
              <div>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </div>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
