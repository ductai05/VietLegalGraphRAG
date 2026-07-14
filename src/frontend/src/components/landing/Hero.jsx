import { Link } from "react-router-dom";
import Reveal from "../Reveal.jsx";
import { useTypewriter } from "../../hooks/useTypewriter.js";
import JusticeScales from "../JusticeScales.jsx";

export default function Hero() {
  // Original markup: "Một CÂU HỎI PHÁP LÝ hoang dã xuất hiện!"
  // The typewriter types the plain text, then the emphasis is restored.
  const typed = useTypewriter("Một CÂU HỎI PHÁP LÝ hoang dã xuất hiện!");
  const done = typed.length >= "Một CÂU HỎI PHÁP LÝ hoang dã xuất hiện!".length;

  return (
    <section className="hero section">
      <div className="container battle-grid">
        <Reveal className="battle-copy">
          <p className="eyebrow">» Cuộc chạm trán AI Pháp lý</p>
          <h1>Aurora</h1>
          <p className="lead">
            Trợ lý pháp luật phong cách pixel, biến câu hỏi của khách hàng, tình tiết vụ việc và
            các mảnh ghép hồ sơ thành bước xử lý tiếp theo rõ ràng — không cần cày cấp.
          </p>
          <div className="hero-actions">
            <Link className="button button-brand" to="/chat">Bắt đầu trò chuyện</Link>
            <a className="button button-secondary" href="#engine">Khám phá công nghệ</a>
          </div>
          <p className="engine-chip">
            Được vận hành bởi <strong>VietLegalGraphRAG</strong>
          </p>
        </Reveal>
        <Reveal className="battle-arena" delay={1} aria-hidden="true">
          <JusticeScales size={72} />
          <div className="dialogue-box">
            {done ? (
              <p className="type-text">
                Một <strong>CÂU HỎI PHÁP LÝ</strong> hoang dã xuất hiện!
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
                alt="Aurora, trợ thủ AI pháp lý của bạn"
              />
              <div className="platform"></div>
            </div>
            <div className="combatant combatant-foe">
              <span className="name-tag">HỒ SƠ VỤ VIỆC</span>
              <img
                className="sprite sprite-float delay"
                src="/case-sprite.svg"
                width="104"
                height="104"
                alt="Một vụ việc pháp lý bất ngờ xuất hiện"
              />
              <div className="platform platform-foe"></div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
