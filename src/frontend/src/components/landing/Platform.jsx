import Reveal from "../Reveal.jsx";

const CARDS = [
  {
    delay: 0,
    fill: "var(--brand)",
    badge: "Tiếp nhận",
    title: "Thu thập tình tiết vụ việc",
    body: "Ghi nhận họ tên, mốc thời gian, hồ sơ nộp, yêu cầu, thời hạn và dấu hiệu rủi ro mà không bắt khách hàng điền biểu mẫu rườm rà.",
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
    badge: "Tra cứu",
    title: "Bản trả lời có trích dẫn nguồn",
    body: "Chuyển câu hỏi mơ hồ thành vấn đề pháp lý cụ thể, sau đó sắp xếp căn cứ pháp luật, lưu ý cần thận trọng và tình tiết chưa rõ.",
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
    badge: "Rà soát",
    title: "Lối duyệt thủ công của con người",
    body: "Chuyển lên luật sư các câu trả lời chưa chắc chắn, nội dung nhạy cảm về bảo mật thông tin và những khoảng trống về thẩm quyền trước khi tư vấn đến tay khách hàng.",
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
          <p className="eyebrow">Nền tảng</p>
          <h2>Xử lý pháp lý với mạch lập luận rõ ràng.</h2>
          <p className="lead">
            Aurora bám sát hồ sơ vụ việc trong suốt cuộc trò chuyện: tình tiết, thẩm quyền,
            vấn đề pháp lý, căn cứ pháp luật và hành động được đề xuất.
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
