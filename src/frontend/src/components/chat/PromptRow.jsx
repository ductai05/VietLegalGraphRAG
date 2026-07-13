const PROMPTS = [
  { prompt: "Summarize my issue for an attorney.", label: "Summarize issue" },
  { prompt: "What documents should I collect?", label: "Document list" },
  { prompt: "What deadlines might matter?", label: "Deadline scan" }
];

export default function PromptRow({ onPrompt, onHandoff }) {
  return (
    <div className="prompt-row" aria-label="Suggested prompts">
      {PROMPTS.map((item) => (
        <button
          type="button"
          key={item.label}
          data-prompt={item.prompt}
          onClick={() => onPrompt(item.prompt)}
        >
          {item.label}
        </button>
      ))}
      <button type="button" data-handoff onClick={onHandoff}>
        Talk to a human
      </button>
    </div>
  );
}
