# Review Rubric — two-stage review, shared by both reviewers (project-agnostic)

Faithful to **obra/superpowers** `task-reviewer-prompt.md` (Stage 1) and `code-reviewer.md` (final),
plus **OneRedOak** design-review (Stage 2). Both reviewers import their severity + method from here so
the pipeline speaks one language. Stack-neutral: "diff", "render", "design system" mean whatever the
project uses.

---

## Why two stages
- **Stage 1 — static (design-spec-reviewer):** cheap, fast, no browser. Catches spec gaps and code
  problems before the expensive visual pass runs.
- **Stage 2 — visual (design-reviewer):** opens the running app in a real browser (Playwright),
  screenshots, and judges the rendered result. Runs **only after Stage 1 is clean**.
- **Final — whole-change (Step 4.5):** one broad review on the most capable model before done.

## Severity taxonomy (two vocabularies, matching each source)
- **Stage 1 → superpowers: Critical / Important / Minor.**
  - *Critical* — bug, broken behavior, security, data loss.
  - *Important* — the change cannot be trusted until fixed: incorrect/fragile behavior, a missed
    requirement, or maintainability damage you'd block a merge over (verbatim logic duplication,
    swallowed errors, tests that assert nothing, raw values where a token exists).
  - *Minor* — polish, "coverage could be broader".
- **Stage 2 → OneRedOak: [Blocker] / [High-Priority] / [Medium-Priority] / Nit:** — same spirit,
  screenshot/viewport-evidenced.

## Two verdicts (Stage 1)
Every static review returns BOTH, independently:
1. **Spec compliance:** `✅` | `❌` | `⚠️` — measured as **Missing / Extra / Misunderstood** vs the brief.
2. **Task quality:** `Approved` | `Needs fixes`.
Both must be clean to advance to Stage 2. A single fix dispatch can address spec gaps + quality findings
together; the re-review covers both.

## Do NOT trust the report (superpowers)
Treat `report.md` as **unverified claims**. Verify against the actual diff/render. A stated rationale
("kept it simple per YAGNI", "left per the brief") is the author grading their own work — it **never
downgrades a finding's severity**. Judge the code/render on its merits.

## ⚠️ Cannot-verify-from-diff (superpowers)
If a requirement lives in unchanged code or spans the change and can't be verified from this diff
alone, report it as a **⚠️ item** rather than crawling the whole codebase. The orchestrator resolves
each (see `handshake-protocol.md` §5).

## Calibration (superpowers)
- Not everything is Critical/Blocker — rate by actual severity.
- **Acknowledge what was done well first** — accurate praise makes the rest of the feedback trusted.
- A brief-mandated thing the rubric calls a defect is still a finding, labeled **brief-mandated** — the
  human decides which governs; don't silently honor or silently override it.
- Every finding cites **file:line** (Stage 1) or **screenshot/viewport/theme** (Stage 2), states what's
  wrong, why it matters, and the concrete fix (referencing the project's design system).
- Inspect code outside the diff only to evaluate a **named** risk (e.g. a changed shared token, an API
  contract, lock ordering) — one focused check per named risk.

## Stage-1 output shape (design-spec-reviewer)
```
## Stage-1 Spec Review — <target>
### Spec Compliance
✅ | ❌ Issues (Missing/Extra/Misunderstood, file:line) | ⚠️ Cannot verify: <what + what to check>
### Strengths
<specific>
### Issues
#### Critical (Must Fix) / #### Important (Should Fix) / #### Minor (Nice to Have)
<each: file:line — what — why — how to fix>
### Assessment
Task quality: Approved | Needs fixes — Reasoning: <1–2 sentences>
```

## Stage-2 output shape (design-reviewer)
```
## Stage-2 Visual Review — <route> — VERDICT: PASS | NEEDS-ITERATION
Overall: <2–3 lines, start with what works>
### [Blocker] / ### [High-Priority] / ### [Medium-Priority] / Nit:
<each: what — evidence (screenshot/viewport/theme) — concrete fix>
```
VERDICT = `PASS` only with **zero** Blockers and **zero** High-Priority items.

## Bias-free dispatch (orchestrator)
Never pre-judge findings in a reviewer dispatch; hand file paths, not pasted diffs; reviewers are
read-only. (See `handshake-protocol.md` §8.)

## Final whole-change review (Step 4.5 — superpowers code-reviewer)
Once the per-change loop passes, run ONE review on the **most capable model (Opus)** over the whole
change diff:
- **Plan alignment** — matches the brief; deviations justified or flagged.
- **Code quality** — separation of concerns, error handling, DRY without premature abstraction, edge cases.
- **Architecture** — sound decisions, integrates cleanly, performance/security sane.
- **Testing** — tests verify real behavior (not mocks); edge cases; all passing.
- **Production readiness** — migration strategy + backward compatibility if backend/schema changed;
  docs; no obvious bugs.
Verdict: **Ready to merge? Yes | No | With fixes.** Findings → ONE consolidated fix dispatch (not one per
finding), then re-verify. Do not give feedback on code you didn't read; be specific (file:line); give a
clear verdict.
