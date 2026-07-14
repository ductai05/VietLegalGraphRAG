import Reveal from "../Reveal.jsx";

const STEPS = [
  { n: "01", title: "Xác định", body: "Xác định thẩm quyền, vai trò các bên, mốc thời gian và mức độ khẩn cấp." },
  { n: "02", title: "Phân tích", body: "Tách bạch tình tiết đã xác nhận với giả định, làm rõ các vấn đề pháp lý có khả năng phát sinh." },
  { n: "03", title: "Chuẩn bị", body: "Soạn bản tóm tắt ngắn gọn, danh mục hồ sơ cần thiết và bàn giao cho luật sư." }
];

export default function Workflow() {
  return (
    <section className="section" id="workflow">
      <div className="container split">
        <Reveal className="section-header">
          <p className="eyebrow">Quy trình</p>
          <h2>Từ tin nhắn đầu tiên đến bản tóm tắt sẵn sàng bàn giao.</h2>
          <p className="lead">
            Trợ lý chỉ hỏi những tình tiết thực sự ảnh hưởng đến phân tích pháp lý, sau đó
            đóng gói cuộc trò chuyện để chuyển cho luật sư.
          </p>
        </Reveal>
        <Reveal className="timeline" delay={1} aria-label="Quy trình làm việc của Aurora">
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
