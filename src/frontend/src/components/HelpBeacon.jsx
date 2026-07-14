import { Link } from "react-router-dom";

export default function HelpBeacon() {
  return (
    <Link className="help-beacon" to="/chat" aria-label="Cần trợ giúp? Trò chuyện với Aurora ngay">
      <span className="ping" aria-hidden="true"></span>
      <span>CẦN TRỢ GIÚP?</span>
    </Link>
  );
}
