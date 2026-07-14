import Reveal from "../Reveal.jsx";
import { useReveal } from "../../hooks/useReveal.js";

const STATS = [
  { fill: "100%", label: "THỜI GIAN HOẠT ĐỘNG", metric: "24/7", caption: "Sẵn sàng tiếp nhận vụ việc mọi lúc, ngày hay đêm." },
  { fill: "100%", label: "RÀ SOÁT", metric: "100%", caption: "Mọi câu trả lời đều tương thích với quy trình rà soát của luật sư." },
  { fill: "0%", label: "RÒ RỈ DỮ LIỆU", metric: "0", caption: "Không rò rỉ dữ liệu — thanh trống chính là mục tiêu.", danger: true }
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
          <p className="eyebrow">Tin cậy</p>
          <h2>Bảng trạng thái: thiết kế để tôn trọng ranh giới pháp lý.</h2>
          <p className="lead">
            Aurora được xây dựng với ngôn từ thận trọng, ý thức về nguồn trích dẫn, rà soát bởi
            con người và lời cảnh báo rõ ràng ở những chỗ cần đến nhận định chuyên môn.
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
