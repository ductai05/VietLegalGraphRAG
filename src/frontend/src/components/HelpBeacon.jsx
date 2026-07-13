import { Link } from "react-router-dom";

export default function HelpBeacon() {
  return (
    <Link className="help-beacon" to="/chat" aria-label="Need help? Talk to Aurora now">
      <span className="ping" aria-hidden="true"></span>
      <span>NEED HELP?</span>
    </Link>
  );
}
