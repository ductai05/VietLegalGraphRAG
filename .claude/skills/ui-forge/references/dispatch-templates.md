# Dispatch Templates — fill-in prompts for each agent (project-agnostic)

Modeled on **obra/superpowers**'s `implementer-prompt.md` / `task-reviewer-prompt.md`. The orchestrator
fills a template and passes it as the `prompt` when spawning an agent. Rules that apply to **every**
dispatch:

- **Name the model explicitly** (`model:` in the Agent call) — never rely on the session default.
- Pass **file paths**, not pasted file contents or session history.
- **Never pre-judge findings** for a reviewer ("treat X as minor", "don't flag Y").
- Give scene-setting: one line on where this fits. Nothing more than the task + interfaces + constraints.
- `[BRACKETS]` = fill in. Keep the return message short; detail goes to the agent's report file.

---

## T1 — ui-context-manager (boot)
```
model: sonnet
description: "Boot UI context"
prompt: |
  Boot mode. Discover this project and write .ui-forge/context.md.
  Follow .claude/skills/ui-forge/references/design-system-discovery.md exactly:
  detect stack + build/dev tooling, the RUN command + URL to open the app for review,
  the design system (framework/tokens/components, or "none — establish one"),
  and the backend API surface already available.
  Answer this specific question the strategist needs: [WHAT THE NEXT STEP NEEDS].
  End with the context.md path, a 5–10 bullet summary, and a status (DONE/NEEDS_CONTEXT/BLOCKED).
```

## T2 — ui-strategist (brief)
```
model: opus
description: "Write Build Brief"
prompt: |
  Read .ui-forge/context.md first, then produce .ui-forge/brief.md for this approved request:
  [CLARIFIED REQUEST + APPROVED DIRECTION].
  Use the reference knowledge base: style-registers.md, ux-guidelines.md, chart-catalog.md,
  component-patterns.md, anti-patterns.md. Obey the project's design system if mature; establish
  tokens (design-system-discovery.md §3) if none.
  The brief must contain: register + dials (variance/motion/density) + family; components (reuse vs new,
  presentation form per chart-catalog, required states); layout & motion; HAVE/NEED data contract;
  reuse notes (by name from context.md); anti-pattern guards; out-of-scope.
  If still ambiguous, return BLOCKED with the open question. End with a status.
```

## T3 — backend-integrator (only if brief has NEED)
```
model: sonnet
description: "Add data to backend"
prompt: |
  The brief .ui-forge/brief.md lists NEED data fields. Read it + context.md (backend section).
  Detect the backend framework and extend it ADDITIVELY and contract-safe: new optional fields or new
  endpoints only; never rename/remove/retype existing ones; typed; thin routes, logic in services;
  match existing patterns; no hardcoded secrets, no swallowed errors, no TODO-and-move-on.
  Classify each NEED as SURFACING (value exists/derivable) or DERIVED/COMPOSITE (score/index/rating/
  health — a product decision). For any derived metric whose formula/inputs/weights/thresholds are NOT
  already in code, do NOT invent one — return BLOCKED with the open definition questions.
  Write the exact new response shape into brief.md's data contract. Verify with a real run
  (import/build/test/curl) and paste the decisive line — no "should work".
  If the data is genuinely unavailable OR a derived metric is undefined, return BLOCKED (do NOT fabricate).
  End with a status.
```

## T4 — ui-implementer (build) — and T4-fix (fix pass)
```
model: sonnet   # cheapest tier only if the brief contains exact code to transcribe
description: "Implement UI change: [SHORT NAME]"
prompt: |
  You are implementing: [SHORT NAME]. Where it fits: [ONE LINE].
  Read .ui-forge/brief.md (your requirements) and .ui-forge/context.md (project map + design system).
  [FIX PASS ONLY: also read the latest findings in .ui-forge/review.md and fix exactly those — nothing more.]
  Before you begin: if anything is unclear (a data field, an approach, a design-system edge case),
  ASK now — return NEEDS_CONTEXT. Don't guess. It is OK to say "this is too hard" and return BLOCKED.
  Implement exactly the brief: obey the project's design system tokens/components, reuse existing
  components before adding new, minimal diff, full state set + a11y contract on every interactive
  element, dark mode via tokens, motion via compositor props with reduced-motion guard.
  Self-review before reporting (completeness / quality / discipline-YAGNI / a11y+dark). Fix issues found.
  Write the full report to .ui-forge/report.md (files changed, components, reuse, review route, concerns).
  Return < ~15 lines: status (DONE/DONE_WITH_CONCERNS/NEEDS_CONTEXT/BLOCKED), changed files, the review
  route/URL, one-line result, concerns, report path.
```

## T5 — design-spec-reviewer (Stage 1, static)
```
model: sonnet
description: "Stage-1 review (spec + quality)"
prompt: |
  Static review of one change — first spec compliance, then code quality. Task-scoped gate, no browser.
  Follow .claude/skills/ui-forge/references/review-rubric.md exactly.
  Read (paths, once): brief .ui-forge/brief.md ; report .ui-forge/report.md (treat as UNVERIFIED claims) ;
  diff = `git diff [BASE]..HEAD`. Binding constraints from the brief: [PASTE VERBATIM].
  Do NOT trust the report; a stated rationale never downgrades a finding. Read-only checkout.
  Part 1 Spec: Missing / Extra / Misunderstood vs the brief; unverifiable-from-diff → ⚠️.
  Part 2 Quality: design-system tokens only (grep the diff), reuse vs duplication, semantics/a11y,
  dark-mode via tokens, hygiene (no dead code/console/leftover). Cite file:line.
  Output the rubric's Stage-1 shape (Spec verdict ✅/❌/⚠️ + Strengths + Critical/Important/Minor +
  Task quality Approved/Needs-fixes). Append to .ui-forge/review.md. End with status DONE.
```

## T6 — design-reviewer (Stage 2, visual)
```
model: sonnet
description: "Stage-2 visual review (Playwright)"
prompt: |
  Open the running app and judge the rendered result against the design system + anti-patterns.
  App URL/route: [URL]. If unreachable, return BLOCKED (do NOT review from source).
  Read .ui-forge/brief.md (intent), the project design system (from context.md), anti-patterns.md,
  ux-guidelines.md. Run phases P0–P7 (prep, interaction, responsive @1440/768/375, visual, dark mode,
  a11y, robustness/empty-loading-error, anti-pattern + outstanding test, console).
  Take REAL screenshots at each viewport + dark. Output the rubric's Stage-2 shape (VERDICT PASS |
  NEEDS-ITERATION, [Blocker]/[High]/[Medium]/Nit, each with evidence + concrete fix). Append to
  .ui-forge/review.md. PASS only with zero Blockers and zero High-Priority.
  If the stack is non-browser (native mobile/desktop) and no web preview/simulator URL is reachable,
  run the static phases and return DEGRADED with the exact manual-screenshot list — never a blind PASS.
  End with status DONE/BLOCKED/DEGRADED.
```

## T7 — final whole-change reviewer (Step 4.5)
```
model: opus
description: "Final whole-change review"
prompt: |
  Broad review of the whole change before done. Follow review-rubric.md's final section.
  What was built: [DESCRIPTION]. Requirements: .ui-forge/brief.md.
  Diff: `git diff [MERGE_BASE]..HEAD` (MERGE_BASE = `git merge-base [MAIN] HEAD`). Read-only.
  Check plan alignment, code quality, architecture, testing, production readiness (migration/backward-
  compat if backend touched). Output Strengths + Issues(Critical/Important/Minor, file:line) +
  Assessment (Ready to merge? Yes|No|With fixes). End with status DONE.
```

## T8 — ui-context-manager (refresh)
```
model: sonnet
description: "Refresh UI context"
prompt: |
  Refresh mode. These files changed: [LIST]. Update only the affected sections of .ui-forge/context.md
  (new components, new tokens/classes, new API fields, changed run command). Append a line to
  .ui-forge/progress.md noting the refresh. End with status DONE.
```

---

## Fix-loop dispatch discipline (superpowers)
- Every fix dispatch carries the implementer contract: fix exactly the findings, self-review, update
  `report.md`. Re-run only the checks covering the change; paste the decisive result.
- Before re-dispatching a reviewer, confirm the fix report contains what changed + the check result.
- Final-review findings → ONE consolidated fix subagent, not one per finding.
