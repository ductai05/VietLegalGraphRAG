import { useState } from "react";
import { Link } from "react-router-dom";

const MATTERS = ["Tiếp nhận vụ việc dân sự", "Rà soát hợp đồng", "Vấn đề lao động", "Kiểm tra thời hạn"];

const STATUS = [
  { term: "Thẩm quyền", value: "Chưa xác định" },
  { term: "Mức độ khẩn cấp", value: "Đang sàng lọc" },
  { term: "Thẩm định", value: "Cần luật sư" }
];

export default function ChatSidebar({ onHandoff }) {
  const [active, setActive] = useState(MATTERS[0]);

  return (
    <aside className="chat-sidebar" aria-label="Bối cảnh vụ việc">
      <Link className="brand" to="/" aria-label="Trang chủ Aurora">
        <img src="/aurora-sprite.svg" alt="" width="40" height="40" />
        <span>Aurora</span>
      </Link>
      <div>
        <p className="sidebar-title">Vụ việc</p>
        <nav className="matter-nav" aria-label="Lối tắt hội thoại">
          {MATTERS.map((matter) => (
            <button
              key={matter}
              type="button"
              className={active === matter ? "active" : undefined}
              onClick={() => setActive(matter)}
            >
              {matter}
            </button>
          ))}
        </nav>
      </div>
      <div className="side-panel">
        <p className="eyebrow">Màn hình trạng thái</p>
        <dl>
          {STATUS.map((row) => (
            <div key={row.term}>
              <dt>{row.term}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
        <div className="side-support">
          <p>Đang gặp khó khăn hoặc cần trao đổi với người thật? Aurora có thể đánh dấu vụ việc này để chuyển tiếp xem xét (bản demo).</p>
          <button
            className="button button-secondary button-small"
            type="button"
            data-handoff
            onClick={onHandoff}
          >
            Yêu cầu chuyển tiếp
          </button>
        </div>
      </div>
    </aside>
  );
}
