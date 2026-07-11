# Anti-Pattern Validation — 3-tier checklist (project-agnostic)

Modeled on **ui-ux-pro-max**'s 3-tier validation. The strategist lists the at-risk items in the brief;
the `design-reviewer` runs the full checklist in Phase 6 before it can return `PASS`; the
`design-spec-reviewer` checks the statically-verifiable ones. Each item is phrased so it applies to any
stack and any design system — check against the project's recorded system, not a hardcoded value.

Severity mapping: an unchecked **Tier-1** or **Tier-3** critical item, or a failed "outstanding" test =
at least `[High-Priority]` and blocks PASS. Tier-2 minor items may be `[Medium]`/`Nit`.

---

## Tier 1 — Visual quality (professional polish)
- [ ] **No emoji as structural icons** — use the project's SVG icon set; consistent family + stroke.
- [ ] **Consistent iconography** — uniform size, stroke width, corner style across the change.
- [ ] **Design-system tokens only** — no raw hex/rgb, no off-scale spacing/radius, no magic numbers
      where a token exists.
- [ ] **Consistent radius & elevation** — follow the system's radius scale and shadow/flat policy; don't
      introduce shadows in a flat system or flatten a system that uses elevation.
- [ ] **Alignment & grid** — elements align to the system's spacing rhythm; optical alignment where
      needed; no 1px drifts.
- [ ] **Pressed/active states cause no layout shift** — transforms/opacity, not size changes that nudge
      neighbors.
- [ ] **Typography hierarchy intact** — correct scale steps, weights, and measure; no fake headings.
- [ ] **Imagery correct** — right aspect ratios, focal points, no stretching/pixelation; brand assets
      unmodified.
- [ ] **Consistency with siblings** — the new UI looks like it belongs with existing screens, not bolted on.

## Tier 2 — Interaction (app-grade experience)
- [ ] **Touch targets ≥44×44px, ≥8px apart.**
- [ ] **Feedback within 80–150ms** of tap/click (state change/optimistic UI); no dead-feeling controls.
- [ ] **Micro-interactions 150–300ms** with natural easing; `prefers-reduced-motion` honored.
- [ ] **Full state set** — every interactive element has hover, visible focus, active, disabled (+
      selected/loading where relevant).
- [ ] **Disabled is clear and inert** — visually distinct and not operable; explains why where possible.
- [ ] **No hover-only essentials** — all essential actions/info reachable by touch and keyboard.
- [ ] **Screen-reader focus order matches visual order**; roving focus in composite widgets.
- [ ] **Async states present** — loading, success, empty, and error for every data-driven view.
- [ ] **No gesture conflicts** — native scroll/back/zoom preserved; no accidental drag/tap collisions.
- [ ] **Input preserved on error**; destructive/irreversible actions confirmed; unsaved-changes guarded.

## Tier 3 — Accessibility & light/dark parity
- [ ] **Contrast** — primary text ≥4.5:1, large/secondary ≥3:1, UI elements ≥3:1, **in both themes**.
- [ ] **Focus visible in both themes** — the indicator has contrast against every background it sits on.
- [ ] **Color never conveys meaning alone** — pair with icon/text/pattern.
- [ ] **Keyboard-complete** — every action reachable and operable; no traps; logical order; skip-link.
- [ ] **Names, roles, values** — controls/regions expose them; live regions announce async changes.
- [ ] **Reduced-motion path** renders the meaningful end state without essential motion.
- [ ] **Dark mode verified independently** with a real screenshot — not inferred from light; driven by
      tokens, not hand-swapped values.
- [ ] **Zoom/reflow** — usable at 200% zoom and 320–375px width without loss of content/function.
- [ ] **Safe areas & fixed bars** — content not obscured by notch/keyboard/sticky bars.
- [ ] **Text scaling** — layout survives larger OS/browser font sizes without truncation/overlap.

## The "outstanding, not generic-AI" test
Beyond the checkboxes — does the result look like a **deliberately designed product for its register**,
or default AI output? Flag if:
- Information is a wall of text where a chart/graph/timeline/stat-tile/card would communicate faster
  (or a heavy chart where a single number would do).
- Spacing is cramped, arbitrary, or off the system's rhythm.
- The change ignores existing components and reinvents them slightly differently.
- The screen feels flat/lifeless where one restrained orchestrated moment would add polish — or busy/
  noisy where restraint is the register.
- The look doesn't match the product's register (see `style-registers.md`).
- Everything is centered, evenly gray, medium-weight, and generic — no clear focal point or hierarchy.

*Restraint executed precisely reads as premium; decoration without purpose reads as amateur. Match the
register — refined for serious domains, expressive for playful ones.*

## Domain-specific escalations (raise a rule's priority when relevant)
- **Trust-critical (legal/finance/health/gov):** sourcing/citations prominent; no misleading charts;
  restrained motion; errors are unambiguous.
- **Data-heavy (analytics/dashboard):** Priority-10 chart rules become HIGH; maximize data-ink; density
  dial high but still scannable.
- **Commerce:** clear CTAs, trust signals, fast perceived performance, no dark patterns.
- **Kids/education:** larger targets, simpler language, forgiving errors, no manipulative flows.
- **Accessibility-regulated (public sector):** treat all Tier-3 items as Blockers.

## Verdict rule
Any unchecked Tier-1/Tier-3 critical item, or a failed outstanding-test, is at least `[High-Priority]`
→ blocks `PASS`. Cite each finding with evidence (screenshot/viewport/theme or file:line) and a concrete
fix referencing the project's design system.
