// Pixel-styled animated "scales of justice" motif.
// Self-contained: reads theme colors from CSS custom properties (see :root
// in styles.css) so it follows the site's palette/dark-mode automatically.
// Not mounted anywhere by default — a parent view wires it into the layout.
export default function JusticeScales({ className = "", size = 140 }) {
  const classes = ["justice-scales", className].filter(Boolean).join(" ");

  return (
    <svg
      className={classes}
      width={size}
      height={size}
      viewBox="0 0 140 140"
      role="img"
      aria-label="Cán cân công lý"
    >
      {/* Stand: base + post + pivot cap (static) */}
      <g className="justice-scales__stand">
        <rect x="45" y="124" width="50" height="8" fill="var(--panel-light)" stroke="var(--border-dark)" strokeWidth="3" />
        <rect x="55" y="116" width="30" height="8" fill="var(--panel-light)" stroke="var(--border-dark)" strokeWidth="3" />
        <rect x="66" y="44" width="8" height="72" fill="var(--panel-light)" stroke="var(--border-dark)" strokeWidth="3" />
      </g>

      {/* Beam + pans: the moving parts */}
      <g className="justice-scales__beam">
        <rect x="20" y="36" width="100" height="8" fill="var(--heading)" stroke="var(--border-dark)" strokeWidth="3" />

        <g className="justice-scales__pan justice-scales__pan-left">
          <rect x="20" y="40" width="4" height="38" fill="var(--border-dark)" />
          <rect x="4" y="78" width="36" height="6" fill="var(--brand)" stroke="var(--border-dark)" strokeWidth="3" />
          <polygon points="6,84 38,84 32,100 12,100" fill="var(--panel-soft)" stroke="var(--border-dark)" strokeWidth="3" />
        </g>

        <g className="justice-scales__pan justice-scales__pan-right">
          <rect x="116" y="40" width="4" height="38" fill="var(--border-dark)" />
          <rect x="100" y="78" width="36" height="6" fill="var(--brand)" stroke="var(--border-dark)" strokeWidth="3" />
          <polygon points="102,84 134,84 128,100 108,100" fill="var(--panel-soft)" stroke="var(--border-dark)" strokeWidth="3" />
        </g>

        <rect x="66" y="34" width="8" height="12" fill="var(--brand)" stroke="var(--border-dark)" strokeWidth="3" />
      </g>
    </svg>
  );
}
