const PROMPTS = [
  { prompt: "Tôi muốn biết quyền lợi của người lao động khi bị chấm dứt hợp đồng.", label: "Quyền lợi lao động" },
  { prompt: "Thủ tục đăng ký kinh doanh hộ cá thể cần những gì?", label: "Đăng ký kinh doanh" },
  { prompt: "Hợp đồng thuê nhà cần lưu ý những điều khoản nào?", label: "Hợp đồng thuê nhà" }
];

export default function PromptRow({ onPrompt, onHandoff }) {
  return (
    <div className="prompt-row" aria-label="Gợi ý câu hỏi">
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
        Trao đổi với người thật
      </button>
    </div>
  );
}
