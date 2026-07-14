import { Link } from "react-router-dom";

export default function Footer() {
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div>
          <Link className="brand brand-inverted" to="/" aria-label="Trang chủ Aurora">
            <img src="/aurora-sprite.svg" alt="" width="40" height="40" />
            <span>Aurora</span>
          </Link>
          <p>Hệ thống chatbot pháp lý xây dựng trên VietLegalGraphRAG, hỗ trợ tiếp nhận thông tin và tra cứu có cấu trúc.</p>
        </div>
        <Link className="button button-light" to="/chat">Mở Chat</Link>
      </div>
    </footer>
  );
}
