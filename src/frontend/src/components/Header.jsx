import { useState } from "react";
import { Link } from "react-router-dom";

// Landing-page sticky header with the mobile menu toggle from app.js.
export default function Header() {
  const [open, setOpen] = useState(false);

  const closeOnNav = () => setOpen(false);

  return (
    <header className="site-header" data-header>
      <Link className="brand" to="/" aria-label="Aurora home">
        <img src="/aurora-sprite.svg" alt="" width="40" height="40" />
        <span>Aurora</span>
      </Link>
      <button
        className="icon-button menu-toggle"
        type="button"
        aria-label="Open navigation"
        aria-expanded={open}
        aria-controls="site-navigation"
        data-menu-toggle
        onClick={() => setOpen((prev) => !prev)}
      >
        <span></span>
        <span></span>
      </button>
      <nav
        className={`site-nav${open ? " is-open" : ""}`}
        id="site-navigation"
        data-nav
        onClick={(event) => {
          if (event.target.closest("a")) {
            closeOnNav();
          }
        }}
      >
        <a href="#platform">Platform</a>
        <a href="#engine">Engine</a>
        <a href="#workflow">Workflow</a>
        <a href="#trust">Trust</a>
        <Link className="button button-tertiary button-small" to="/chat">
          Open Chat
        </Link>
      </nav>
    </header>
  );
}
