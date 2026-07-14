# Chart & Visualization Catalog — viz-first information design (project-agnostic)

Modeled on **ui-ux-pro-max**'s 25-chart database. Core principle: **information deserves the richest
fitting visual form.** When a request says "show X", map X's data shape to a form below **before**
writing a paragraph. Plaintext is the fallback, not the reflex — but never force a viz where plain text
is the honest form (a legal clause, a quote, a short status message, a single sentence of guidance).

The strategist picks the form; the implementer builds it in the project's stack; both reviewers check
the "chart-*" rules in `ux-guidelines.md`. Build order of preference: **native/CSS/SVG → the project's
existing chart lib → a new lightweight lib (justified, lazy-loaded)** (`perf-bundle`).

---

## A. Decision by data question
| The user wants to… | Best form(s) | Avoid |
|--------------------|--------------|-------|
| Show one key figure | **Stat tile / KPI** (number + label + optional delta/sparkline) | burying it in a sentence |
| Compare items | **Bar** (vertical ≤ ~7, horizontal for many/long labels) | pie for comparison |
| Show a trend over time | **Line / Area** (area for volume, multi-line for few series) | bar for continuous time |
| Show parts of a whole | **Stacked bar / 100% stacked / Donut** (donut ≤ 4–5 slices) | pie with many slices |
| Show distribution | **Histogram / Box plot / Violin** | averages hiding spread |
| Show correlation | **Scatter** (add trendline), **Bubble** (3rd dim = size) | dual-axis implying causation |
| Show flow / conversion | **Funnel / Sankey** | stacked bars for flow |
| Show progress toward a goal | **Progress bar / Gauge / Radial** | a bare percentage in text |
| Show a value vs range/target | **Bullet chart / Meter** | gauge that wastes space |
| Show relationships/network | **Node-link graph / Force graph / Chord** | prose describing links |
| Show hierarchy | **Treemap / Sunburst / Tree** | nested bullet lists for big trees |
| Show magnitude over 2 categories | **Heatmap** | a dense number table |
| Show geographic data | **Choropleth / Symbol map** | table of places |
| Show a schedule/sequence | **Timeline / Gantt** | numbered paragraphs |
| Show ranked results w/ scores | **Ranked cards + score meter/bar** | plain ordered list |
| Show change between 2 states | **Slope chart / Dumbbell** | two separate bars |
| Show a single ratio/proportion | **Donut(1) / Pictograph** | pie of two slices |

## B. Non-chart rich forms (often better than a chart)
- **Stat tile / KPI row** — headline numbers with label, trend delta, tiny sparkline.
- **Card grid** — heterogeneous items (results, entities, docs) as scannable cards.
- **Ranked list with meters** — search/recommendation results with a relevance bar/score badge.
- **Citation / source card** — attribution: title, locator, snippet, link — for RAG/research/legal.
- **Timeline** — events/versions/history in temporal order.
- **Badge / chip / tag** — categorical status, intent, labels (pair with icon/text, not color-only).
- **Meter / progress** — confidence, completeness, quota.
- **Comparison table** — 2–N items across attributes (with a horizontal scroll container on mobile).
- **Accordion / tabs** — long structured content split into scannable sections.
- **Stepper / pipeline** — a process or multi-stage flow.
- **Empty/skeleton state** — a designed empty/loading state is information too.

## C. Per-form spec (when to use · encode · a11y · build · responsive)
Each entry: **When** · **Encode** · **A11y** · **Build** · **Responsive**.

- **Stat tile** — When: 1–6 headline metrics. Encode: big number, muted label, signed delta (↑/↓ +
  text, not color-only), optional sparkline. A11y: real text, not an image. Build: native markup + a
  tiny inline SVG sparkline. Responsive: wrap/stack.
- **Bar (vertical)** — When: compare ≤ ~7 discrete items. Encode: length; baseline at 0; direct value
  labels beat a distant axis. A11y: label bars; provide a table fallback. Build: CSS flex bars or SVG.
  Responsive: switch to horizontal when labels crowd.
- **Bar (horizontal)** — When: many items or long labels; rankings. Encode: length + label at start.
  Build: CSS/SVG. Responsive: scrollable list on mobile.
- **Line** — When: continuous trend, few series. Encode: position; consistent time axis; markers at
  points. A11y: legend + values on hover/focus; table fallback. Build: SVG path. Responsive: reduce
  ticks; enable horizontal scroll if dense.
- **Area / Stacked area** — When: volume over time / composition over time. Encode: filled region;
  order stacks by stability. Avoid: too many bands (>4). Build: SVG. 
- **Donut** — When: one proportion or ≤4–5 parts of a whole. Encode: arc length; center shows the key
  number. Avoid: many thin slices. Build: SVG arcs. 
- **Scatter / Bubble** — When: correlation / 2–3 dimensions. Encode: x, y (+ size, + label). A11y:
  tooltips; don't rely on color alone for groups. Build: SVG circles.
- **Funnel / Sankey** — When: stage-to-stage conversion / flow volumes. Encode: width = magnitude;
  label drop-off. Build: SVG; Sankey may warrant a lib.
- **Progress / Gauge / Radial / Bullet / Meter** — When: value vs goal/range. Encode: filled proportion
  + numeric label + target marker (bullet). A11y: `role="progressbar"` + aria values. Build: CSS/SVG.
- **Node-link / Force graph** — When: entities & relationships (graph data, dependencies, knowledge
  graphs). Encode: nodes (size/label), edges (weight/direction). A11y: provide a list/table alternative;
  keyboard-focusable nodes. Build: lightweight SVG/canvas force layout; heavy graphs → a lean lib,
  lazy-loaded. Responsive: allow pan/zoom; simplify on small screens.
- **Treemap / Sunburst / Tree** — When: hierarchy + magnitude. Encode: area/arc = value; nesting =
  hierarchy. Build: SVG or a lib for big trees.
- **Heatmap** — When: magnitude across two categorical axes. Encode: cell intensity (+ value label on
  hover); use a perceptually-uniform sequential ramp, colorblind-safe. Build: CSS grid or SVG.
- **Choropleth / map** — When: geography matters. Needs a geo lib + accessible fallback table.
- **Timeline / Gantt** — When: events/tasks over time. Encode: horizontal time axis; bars/markers with
  labels. Build: CSS grid/SVG. Responsive: vertical timeline on mobile.
- **Ranked cards + meter** — When: search/recommendation/eval results. Encode: rank, title, a score
  meter/badge, snippet, source link. Build: native card + CSS meter. Responsive: single column.
- **Slope / Dumbbell** — When: change between two points/states across items. Encode: two points + line.
  Build: SVG.
- **Comparison table** — When: structured attribute comparison. Encode: rows=items, cols=attributes,
  highlight winners with icon+text. A11y: `<th scope>`, caption. Responsive: horizontal scroll wrapper.

## D. Motion for data (respect the motion dial + reduced-motion)
- Reveal charts with a short (200–400ms) ease-out draw/grow; count-up numbers on first view.
- Prefer one orchestrated entrance over per-element bouncing. Never animate `width/height` — animate
  `transform: scaleX`/`opacity` (`perf-animation-compositor`).
- Under `prefers-reduced-motion`, render the final state immediately.

## E. Color for data
- **Signal, not decoration.** Use the design system's data/accent tokens; keep chrome muted so data
  stands out (maximize data-ink).
- **Never color-only.** Distinguish series by pattern/shape/label/position as well (`chart-accessible-color`).
- **Sequential vs diverging vs categorical** — pick the ramp type that matches the data; keep categorical
  palettes small and distinguishable; verify in light and dark.
- If the project is monochrome/minimal, differentiate by fill/opacity/position/label — not hue.
- For construction details (scales, tick logic, accessible palettes) consult the built-in **`dataviz`
  skill**, but override its palette with the project's design tokens.

## F. The reviewer's test
If the built result is a wall of text where a chart/graph/timeline/stat-tile/card would communicate
faster — or a heavy chart where one number would do — the `design-reviewer` flags it (Phase 6,
"outstanding, not generic-AI") and it blocks PASS.
