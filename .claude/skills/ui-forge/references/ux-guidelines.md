# UX Guidelines — enumerated 10-priority ruleset (project-agnostic)

Modeled on **ui-ux-pro-max**'s 99-guideline database, ordered by impact (1 = highest). Each rule has an
id, the **must-have** check, the **anti-pattern** to avoid, and the standard it derives from. The
strategist folds at-risk rules into the brief's guards; `design-spec-reviewer` checks the static ones
(markup/CSS/props); `design-reviewer` checks the runtime ones (browser). Severity: violating a
**CRITICAL/HIGH** rule is a Blocker/High-Priority; MEDIUM/LOW are Medium/Nit unless they break intent.

Applies to any stack — translate "focus ring", "contrast", "target size" into the project's idiom.

---

## Priority 1 — Accessibility · CRITICAL
- **a11y-contrast** — Body text contrast ≥ 4.5:1; large text (≥24px or ≥19px bold) ≥ 3:1; UI/graphical
  elements ≥ 3:1. *Anti:* gray-on-gray, low-contrast placeholder-as-content. *WCAG 1.4.3/1.4.11.*
- **a11y-focus-visible** — Every interactive element has a clearly visible focus indicator; never
  remove outlines without replacing them. *Anti:* `outline: none` with no substitute. *WCAG 2.4.7.*
- **a11y-keyboard** — All functionality operable by keyboard; logical tab order; no keyboard traps.
  *Anti:* click-only controls, custom widgets you can't Tab to. *WCAG 2.1.1/2.1.2.*
- **a11y-semantics** — Use native semantic elements (`button`, `a`, `nav`, `main`, `h1–h6` in order,
  lists, `table`); ARIA only to fill gaps, never to replace semantics. *Anti:* `div` with onclick,
  skipped heading levels. *WCAG 1.3.1/4.1.2.*
- **a11y-labels** — Every control has an accessible name (visible `label`+`for`/`id`, `aria-label`, or
  `aria-labelledby`); icon-only buttons get a text alternative. *Anti:* icon buttons with no name.
- **a11y-alt** — Meaningful images have `alt`; decorative images have empty `alt=""`/are backgrounds.
  *Anti:* `alt="image"`, missing alt on informative graphics.
- **a11y-target-name-role-value** — Custom components expose role/state/value to AT (e.g. `aria-expanded`,
  `aria-selected`, `aria-checked`). *Anti:* a toggle that never announces on/off.
- **a11y-live-regions** — Async status/errors announced via `aria-live`/`role="status"`/`role="alert"`.
  *Anti:* silent spinner, error appears only visually.
- **a11y-reduced-motion** — Honor `prefers-reduced-motion`; disable non-essential animation. *WCAG 2.3.3.*
- **a11y-lang-direction** — Document `lang` set; support RTL if the product needs it; don't hardcode LTR.

## Priority 2 — Touch & Interaction · CRITICAL
- **touch-target-size** — Interactive targets ≥ 44×44px (iOS) / 48×48dp (Android) / ≥24px min (WCAG 2.5.8).
  *Anti:* tiny tap zones, links packed tightly.
- **touch-spacing** — ≥ 8px between adjacent targets. *Anti:* overlapping/adjacent buttons.
- **interaction-feedback** — Visible feedback within 80–150ms of tap/click (ripple, state change,
  optimistic UI). *Anti:* instant 0ms state change with no acknowledgment; dead-feeling buttons.
- **interaction-states** — Every interactive element defines hover, focus, active, disabled (and
  selected/loading where relevant). *Anti:* only a default state.
- **interaction-no-hover-only** — Never hide essential actions/info behind hover only (fails touch &
  keyboard). *Anti:* menus that open on hover with no click/focus path.
- **interaction-no-layout-shift** — Pressed/active/expanded states must not shift surrounding layout.
  *Anti:* button grows on press and nudges siblings.
- **interaction-gesture-safety** — Don't override native gestures (back-swipe, scroll, pinch-zoom);
  no conflicting tap/drag/long-press on the same element without affordance.

## Priority 3 — Performance · HIGH
- **perf-image-format** — Serve modern formats (WebP/AVIF), correct dimensions, `srcset`; compress.
  *Anti:* full-res JPEG/PNG scaled down in CSS.
- **perf-lazy-load** — Lazy-load offscreen images/heavy components; code-split routes. *Anti:* eager
  loading a charting/3D lib on first paint.
- **perf-cls** — Reserve space for media/embeds so Cumulative Layout Shift < 0.1 (width/height or
  aspect-ratio). *Anti:* images without dimensions causing reflow.
- **perf-main-thread** — Keep interactions responsive (INP < 200ms); avoid long tasks; debounce/throttle.
  *Anti:* synchronous heavy work on input.
- **perf-animation-compositor** — Animate only `transform`/`opacity`; avoid animating layout props
  (`width/height/top/left`). *Anti:* animating `width` in a loop → jank.
- **perf-font-loading** — `font-display: swap`, preload critical fonts, subset. *Anti:* invisible text
  (FOIT) blocking render.
- **perf-bundle** — Prefer CSS/SVG/native before pulling a JS library; if unavoidable, keep it lean and
  lazy. *Anti:* a 200KB dep for one sparkline.

## Priority 4 — Style Selection · HIGH
- **style-match-register** — The look matches the product register (see `style-registers.md`).
  *Anti:* playful/neon on a trust-critical domain; generic "AI SaaS" on everything.
- **style-consistency** — Reuse the design system's tokens/components; consistency across screens.
  *Anti:* per-screen raw hex, ad-hoc spacing, one-off components duplicating existing ones.
- **style-icons** — Use a single consistent SVG icon set with uniform stroke/size; **no emoji as
  structural icons**. *Anti:* emoji icons, mixed icon families.
- **style-no-mixed-metaphors** — Don't mix incompatible style families (flat + skeuomorphic) in one
  surface. *Anti:* a flat UI with one heavily-shadowed skeuomorphic card.
- **style-imagery** — Consistent, high-quality imagery with correct aspect ratios and focal points.
  *Anti:* stretched/pixelated images, inconsistent treatment.
- **style-brand-assets** — Use official brand assets at correct proportions/clear-space. *Anti:*
  recoloring/distorting logos.

## Priority 5 — Layout & Responsive · HIGH
- **layout-mobile-first** — Design mobile-first; scale up at breakpoints. *Anti:* desktop-only layout
  that breaks on phones.
- **layout-no-h-scroll** — No unintended horizontal scroll at 320–375px; content reflows. *Anti:*
  fixed-px wide containers, wide tables without a scroll container.
- **layout-viewport-meta** — `<meta viewport>` present; **don't disable zoom** (`user-scalable=no`).
- **layout-reflow** — Use fluid grids/flex; column→row reflow; `max-width` on media. *Anti:* absolute
  positioning that overlaps at breakpoints.
- **layout-safe-areas** — Respect notches/home indicators/keyboards (`env(safe-area-inset-*)`); content
  not hidden behind fixed bars. *Anti:* CTA under the home indicator.
- **layout-spacing-rhythm** — Consistent spacing on the system's base grid (4/8px); align to a rhythm.
  *Anti:* arbitrary 13px/27px gaps.
- **layout-line-length** — Body copy ~45–75 characters per line. *Anti:* full-width paragraphs on wide
  screens.

## Priority 6 — Typography & Color · MEDIUM
- **type-base-size** — Body ≥ 16px; line-height ~1.5; comfortable paragraph spacing. *Anti:* 12px body.
- **type-scale** — Use a modular scale; clear hierarchy; limited weights. *Anti:* many arbitrary sizes.
- **type-hierarchy** — Distinct, ordered heading levels; one `h1` per view. *Anti:* size-only fake
  headings with no semantics.
- **type-measure-tracking** — Tracking tight for large display, ~0 for body; no tracking on small text.
- **color-semantic-tokens** — Use semantic color roles/tokens, not raw hex per component. *Anti:*
  `#3B82F6` sprinkled in components.
- **color-limited-palette** — Restrained palette; don't introduce colors outside the system. *Anti:*
  rainbow accents competing for attention.
- **color-not-alone** — Never encode meaning by color alone — pair with icon/text/pattern. *Anti:*
  red/green-only status. *WCAG 1.4.1.*
- **color-dark-mode** — If dark mode exists, verify both themes; drive it via tokens, don't hand-swap.

## Priority 7 — Animation · MEDIUM
- **anim-duration** — 150–300ms for UI transitions; enter slightly slower than exit. *Anti:* 1s+ UI
  transitions, or 0ms with no continuity.
- **anim-meaning** — Motion conveys meaning (spatial continuity, cause/effect, focus), not decoration.
  *Anti:* things that move for no reason.
- **anim-orchestration** — Prefer one well-sequenced moment (staggered reveal) over many scattered
  micro-animations. *Anti:* everything bouncing independently.
- **anim-easing** — Natural easing (ease-out/standard curves); no linear for physical motion.
- **anim-reduced-motion** — Provide a reduced/none variant under `prefers-reduced-motion` (see a11y).
- **anim-perf** — Compositor-only properties (see perf-animation-compositor).

## Priority 8 — Forms & Feedback · MEDIUM
- **form-visible-labels** — Always-visible labels; **placeholder is not a label**. *Anti:* placeholder-
  only fields that lose context on input.
- **form-inline-errors** — Errors shown next to the field, specific and actionable, announced to AT.
  *Anti:* one generic error at the top.
- **form-helper-text** — Format hints/constraints shown before submission. *Anti:* discovering rules
  only on failure.
- **form-input-types** — Correct input types/`inputmode`/`autocomplete`; native pickers where apt.
  *Anti:* plain text field for dates/emails/phones.
- **form-progressive-disclosure** — Reveal complexity progressively; group logically; sensible defaults.
  *Anti:* a 40-field wall.
- **form-feedback-states** — Every async action has loading, success, empty, and error states. *Anti:*
  no loading indicator; blank screen while fetching.
- **form-preserve-input** — Don't clear user input on error; preserve and highlight.
- **form-prevent-loss** — Warn before discarding unsaved changes / destructive actions; confirm
  irreversible ones. *Anti:* silent data loss.

## Priority 9 — Navigation · HIGH
- **nav-predictable-back** — Back behaves predictably; deep-linkable URLs/routes; state restored.
  *Anti:* back exits the app / loses context.
- **nav-current-location** — Clear active/current indicator; breadcrumbs for depth. *Anti:* "where am I?"
- **nav-limited-primary** — ≤ ~5 primary nav items (bottom-nav/top-nav); overflow into a menu. *Anti:*
  overloaded nav bars.
- **nav-labels-not-mystery** — Labeled navigation; no mystery-meat icon-only nav without labels/tooltips.
- **nav-consistent-placement** — Navigation in consistent, expected locations across screens.
- **nav-skip-link** — Provide a "skip to content" link for keyboard/AT users.

## Priority 10 — Charts & Data · (elevate when the product is data-heavy)
- **chart-right-type** — Match chart type to the data question (see `chart-catalog.md`). *Anti:* pie with
  12 slices; dual-axis to imply false correlation.
- **chart-legend-tooltip** — Legends and tooltips present; direct labels preferred over distant legends.
- **chart-accessible-color** — Distinguish series by more than color (pattern/label/shape); colorblind-safe.
  *Anti:* color-only series.
- **chart-honest-scales** — Truthful axes (baseline at 0 for bars), no truncation that misleads, note
  units. *Anti:* truncated y-axis exaggerating differences.
- **chart-responsive** — Charts reflow/scroll gracefully on small screens; readable labels or a mobile
  variant. *Anti:* a 12-series line chart crammed into 320px.
- **chart-vs-text** — Use a chart when it communicates faster than text; use a single number/stat tile
  when that's clearer; don't force a chart where a sentence wins, or a wall of text where a chart wins.

---

## How to use this file
- **Strategist:** list the rules most at risk for this change under the brief's "anti-pattern guards".
- **design-spec-reviewer (static):** enforce Priorities 1 (markup), 4, 5 (CSS/layout), 6, 8 (form
  markup), plus semantic parts of 2 and 10.
- **design-reviewer (browser):** enforce runtime parts of 1 (focus/contrast/keyboard live), all of 2,
  3, 5 (responsive at real viewports), 7, 9, 10, and the empty/loading/error states of 8.
- Translate every rule into the project's design system tokens and stack idioms — never hardcode a
  specific value the project's system doesn't use.
