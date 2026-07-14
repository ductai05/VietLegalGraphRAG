# Component Patterns Catalog — anatomy, states & rules (project-agnostic)

A reference for the strategist (choose the right component) and the implementer (build it correctly)
and the reviewers (know the required states). It is **structural, not stylistic** — it says what a
component *is made of* and *which states it must have*; the concrete look comes from the project's
design system (`design-system-discovery.md`). If the project has the component already, **reuse it** —
this catalog is the checklist, not a mandate to build new.

Universal rule: **every interactive component defines default · hover · focus-visible · active ·
disabled**, plus any of selected/loading/error/empty that apply. Every component is keyboard-operable
and exposes role/name/state to assistive tech.

---

## Actions & inputs
- **Button** — variants: primary / secondary / tertiary / ghost / destructive / icon-only. States:
  default·hover·focus·active·disabled·loading (spinner + disabled). Rules: real `<button>`; label or
  aria-label; min target size; no layout shift on press; destructive gets confirmation.
- **Button group / segmented control** — grouped exclusive/multi actions; one shared silhouette; each
  child keeps focus states; indicate the selected segment by more than color.
- **Link** — real `<a>` with href; visible + distinguishable from body text; focus/hover; external links
  indicated; never use a link as a button (or vice-versa).
- **Text input / textarea** — anatomy: visible label, field, helper text, error text, optional
  leading/trailing icon. States: default·hover·focus·filled·disabled·error·success. Rules: label tied
  by `for`/`id`; placeholder ≠ label; correct type/inputmode/autocomplete; inline errors announced.
- **Select / combobox / autocomplete** — keyboard navigable list; typeahead; selected + active-descendant
  exposed; empty/no-results state; loading state for async options.
- **Checkbox / radio / switch** — 44px hit area even if the control is small; label clickable; group
  with fieldset/legend or `role=radiogroup`; switch announces on/off; indeterminate for checkboxes.
- **Slider / range** — keyboard arrows; `aria-valuenow/min/max`; visible value; large enough thumb.
- **Date / time picker** — native where possible; keyboard entry; clear format hint; timezone clarity.
- **File upload / dropzone** — click + drag; accepted types/size shown; progress; success/error per file.
- **Search** — input + clear button + submit; recent/suggestions; empty and no-results states.

## Containers & surfaces
- **Card** — surface holding related content; optional header/media/body/footer/actions. Static vs
  interactive (interactive gets hover/focus + is a real link/button); consistent radius/elevation from
  the system.
- **List / list item** — vertical rhythm; leading icon/avatar, primary + secondary text, trailing
  action/meta; dividers or spacing; selectable rows expose selection.
- **Table** — `<caption>`, `<thead>` with `<th scope="col">`, row headers `scope="row">`; horizontal
  scroll container on small screens; optional sort (announce sort state), pagination, empty state,
  sticky header. Don't fake a table with divs.
- **Accordion** — trigger is a `<button>` with `aria-expanded` + `aria-controls`; one-open or multi;
  chevron rotates; content region labelled.
- **Tabs** — `role=tablist/tab/tabpanel`; arrow-key navigation; active tab exposed; content swaps
  without layout jump; consider not-hidden content for SEO/AT where relevant.
- **Modal / dialog** — `role=dialog` + `aria-modal`; focus trap; restore focus on close; Esc closes;
  scrim; scroll lock; not for non-blocking messages (use a toast). Confirmation dialogs for destructive.
- **Drawer / sheet / popover / dropdown menu** — anchored overlays; focus management; click-outside +
  Esc; `role=menu` for menus with arrow-key nav; position-aware (flip/shift).
- **Tooltip** — supplementary only (never sole source of essential info); focus + hover triggered;
  dismissible; not on touch-only critical paths.
- **Toast / snackbar / inline alert** — transient (toast) vs persistent (inline alert); `role=status`
  (polite) or `role=alert` (assertive); action affordance; don't stack endlessly.
- **Banner / callout** — page-level info/warning/success/danger; icon + text (not color-only); dismissible
  where appropriate.

## Navigation & structure
- **Top nav / navbar** — brand, primary links (≤~5), actions; current-page indicator; responsive
  collapse to a menu; skip-link target.
- **Sidebar / rail** — sections, nav items with active state, collapse/expand, keyboard nav; overflow
  scroll; mobile off-canvas with a trigger.
- **Bottom nav (mobile)** — ≤5 items, icon + label, active state, safe-area aware.
- **Breadcrumbs** — show depth/location; last item is current (not a link); truncate gracefully.
- **Pagination / infinite scroll** — clear current page, prev/next, jump; for infinite scroll provide a
  "load more" fallback and preserve scroll on back.
- **Stepper / wizard** — steps with completed/current/upcoming states; allow back; validate per step.

## Data display & feedback
- **Stat tile / KPI**, **charts**, **meters/progress**, **timelines**, **badges/chips**, **avatars**,
  **ranked result cards**, **citation cards** — see `chart-catalog.md` for when/encode/build.
- **Skeleton / loading** — layout-preserving placeholders; match final layout to avoid CLS; paired with
  `aria-busy`/live region.
- **Empty state** — icon/illustration + explanation + a primary action; never a blank region.
- **Error state** — what happened + how to recover/retry; don't dead-end.
- **Avatar** — image with `alt`/initials fallback; consistent shape/size; presence/status indicated by
  more than color.

## Motion & feedback rules (cross-cutting)
- Transitions 150–300ms, ease-out, compositor-only props; one orchestrated moment over scattered ones;
  reduced-motion variant. (See `ux-guidelines.md` Priority 7.)

## How to use
- **Strategist:** name the components the change needs, mark each **reuse existing `<Name>`** or **new**,
  and list required states in the brief.
- **Implementer:** build each with its full state set + a11y contract; reuse the project's component
  before adding a new one; match the system's tokens.
- **Reviewers:** verify every interactive component has default/hover/focus/active/disabled (+ relevant
  loading/empty/error) and the a11y contract; a missing focus or empty/error state is a finding.
