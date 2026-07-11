---
name: ui-forge
description: Project-agnostic multi-agent workflow for frontend/UI work in ANY stack (React, Vue, Svelte, Angular, Astro, vanilla, native, etc.). Use whenever the user wants to add/change/remove UI or UX, show information on a screen, restyle components, build a page/section, or improve look & feel. It discovers the project's stack and design system (or establishes one), clarifies ambiguity before coding (no hallucination), decides a context-aware design via a design-intelligence brief (Opus), implements it (Sonnet), then runs a two-stage review — static spec/code review then a real-browser Playwright visual loop — until it passes, and gates on fresh verification before declaring done.
---

# ui-forge — project-agnostic multi-agent UI workflow

## What this solves
One-shot "prompt-and-pray" UI work produces mediocre results because the agent **cannot see** what it
built, has **no design taste calibrated to the product**, and **guesses** when the request is vague —
forcing a manual re-prompt loop that burns time and tokens. ui-forge fixes all three:

- **Eyes** — a Playwright review agent screenshots the running UI and iterates against the design system.
- **A design brain** — a strategist derives the right visual register and information design, using a
  reference knowledge base, before a line of code is written.
- **A clarify/brainstorm gate** — ambiguity is resolved (and a direction approved) up front; the agent
  asks instead of hallucinating.
- **Coordination that scales** — a shared context broker, file handoffs, a progress ledger, a two-stage
  review, and a verification gate keep quality high and context lean. **Opus decides, Sonnet builds.**

## Design principles (why it is built this way)
1. **Project-agnostic.** Nothing here assumes a framework, language, backend, or design system. The
   context-manager *discovers* them at runtime (see `references/design-system-discovery.md`). If the
   project already has a design system, ui-forge **obeys** it; if not, the strategist **establishes**
   a lightweight one from a register profile and records it so future runs are consistent.
2. **See before done.** No UI is called finished without a real-browser screenshot verifying it.
3. **Ask before build.** Ambiguous → clarify + get a direction approved. Hallucinated scope is the
   worst outcome.
4. **Separation of concerns.** Each agent owns one job in its own clean context; they communicate
   through files, not by inheriting each other's history.
5. **Evidence over assertion.** "Done" requires fresh proof, every time.

## When to use / not use
Use for any user-facing UI/UX change. Skip for pure backend/data/infra/algorithm work with no visible
surface (though ui-forge *can* drive a backend change when the UI needs new data — Step 3).

## Orchestration model
You (this skill, on Opus) are the **orchestrator**. You never write product code yourself — you
dispatch subagents, pass them **file paths** (not pasted history), read their status returns, resolve
blockers, and drive the loop. The subagents live in `.claude/agents/`. Read these references before
orchestrating:
- `references/handshake-protocol.md` — the `.ui-forge/` workspace, file handoffs, status codes, ledger.
- `references/dispatch-templates.md` — fill-in prompt templates for each dispatch.
- `references/review-rubric.md` — severity taxonomy, two verdicts, do-not-trust, ⚠️ handling.

## Decision tree

```
UI/UX request
  │
  ├─ Step -1 RESUME CHECK — does .ui-forge/progress.md exist?
  │     └─ yes ─▶ read the ledger + `git log --oneline`; tasks marked complete are DONE
  │              (don't re-ask answered questions, don't re-dispatch done steps); resume at
  │              the first incomplete step below
  │
  ├─ Is the request concrete AND is a direction approved?
  │     └─ no ─▶ Step 0 CLARIFY/BRAINSTORM GATE (loop until yes)
  │
  ├─ Does .ui-forge/context.md exist and is it current?
  │     └─ no ─▶ Step 1 BOOT/REFRESH CONTEXT
  │
  ├─ Step 2 DESIGN BRIEF (strategist)
  │
  ├─ Does the brief's data contract have NEED fields?
  │     └─ yes ─▶ Step 3 BACKEND INTEGRATION
  │
  ├─ Step 4 BUILD + TWO-STAGE REVIEW LOOP  (build → static review → visual review → fix)
  │
  ├─ Step 4.5 FINAL WHOLE-CHANGE REVIEW (Opus)
  │
  └─ Step 5 VERIFY-BEFORE-DONE GATE ─▶ report to user
```

---

## The pipeline

### Step -1 — RESUME CHECK (you, Opus) — before anything else, every invocation
Conversation memory does not survive context compaction or a new session; the ledger does. **First
action:** `cat .ui-forge/progress.md` (per `handshake-protocol.md` §6/§9). If it exists:
- Read it plus `git log --oneline` for the named commit range; reconcile what the ledger says is done
  against git.
- Tasks/rounds marked complete are **DONE** — do **not** re-ask already-answered clarifying questions,
  do **not** re-dispatch completed steps, do **not** rebuild. Also re-read `context.md` and `brief.md`
  if present (the approved direction and clarified intent live there — don't re-run Step 0 for them).
- Resume at the first step not marked complete.
If there's no ledger, this is a fresh run — create `.ui-forge/`, then continue to Step 0.

### Step 0 — CLARIFY / BRAINSTORM GATE (you, Opus) — do FIRST, every time
Read `references/clarify-gate.md`. **Triage the request into Tier A/B/C first** (clarify-gate.md
"Ambiguity triage") and size the gate to it — this is the fix for both over-asking and under-asking:
- **Tier A (low ambiguity, design system answers it):** fast-path — 0–1 decisive question, then a
  **one-line confirm**; do NOT manufacture 2–3 alternatives. Then proceed.
- **Tier B (medium):** 1–3 questions + one recommended direction to confirm.
- **Tier C (high — vague intent, register shift, multiple screens, undefined/derived data):**
  **`AskUserQuestion`** with concrete options (loop, batches of ≤4, narrowing each round) + **2–3
  directions with `preview` trade-offs**, recommend one, get approval.
- The **invariant** (all tiers): *no product code until intent is confirmed* — the confirm may be one
  line for Tier A, but it must exist. **Never guess to avoid asking.** This gate is also where any
  downstream `BLOCKED`-on-scope returns.

### Step 1 — BOOT / REFRESH CONTEXT (ui-context-manager, Sonnet)
Dispatch `ui-context-manager`. In **boot** mode it writes `.ui-forge/context.md`: detected stack &
build tooling, frontend location, **design system** (framework/tokens/components discovered, or "none
— establish one"), how to run the app locally for review, and the backend API surface already
available. Every later agent reads this instead of re-scanning — this keeps cold subagents cheap and
consistent. Use **refresh** mode after edits to update only the changed sections.

### Step 2 — DESIGN BRIEF (ui-strategist, Opus)
Dispatch `ui-strategist`. Using context.md + the reference knowledge base (`style-registers.md`,
`ux-guidelines.md`, `chart-catalog.md`, `component-patterns.md`, `anti-patterns.md`), it writes
`.ui-forge/brief.md`: visual register + design dials, viz-first component choices, layout/motion,
HAVE/NEED data contract, reuse notes, anti-pattern guards, out-of-scope. **If the project has a design
system, the brief targets its tokens; if not, the brief establishes tokens.** If the strategist
returns `BLOCKED` (still ambiguous) → back to **Step 0**.

### Step 3 — BACKEND INTEGRATION (backend-integrator, Sonnet) — only if brief has NEED fields
Dispatch `backend-integrator`. It detects the backend stack, extends it **additively** (typed,
contract-safe, backward-compatible), and writes the new response shape back into the brief. If it
returns `BLOCKED` (data genuinely unavailable) → back to **Step 0** to re-clarify scope. Never let the
implementer fabricate data.

### Step 4 — BUILD + TWO-STAGE REVIEW LOOP (subagent-driven)
Read `references/review-rubric.md`. **Pre-flight:** scan `brief.md` once for internal contradictions
or anything it mandates that the rubric would treat as a defect; batch those to the user as one
question. Clean → proceed silently. Then loop (cap ~3 rounds), continuous execution — no check-ins
between rounds:

1. **Build** — dispatch `ui-implementer` (Sonnet) via the template in `dispatch-templates.md`. It
   self-reviews, writes `.ui-forge/report.md`, returns status + changed files + review route. Handle
   the status per `handshake-protocol.md` (context→re-dispatch; complexity→upgrade to Opus; scope→
   Step 0).
2. **Stage 1 — static review** — record BASE commit; dispatch `design-spec-reviewer` (Sonnet) with
   file paths (brief, report, diff). It returns **two verdicts** (Spec `✅/❌/⚠️` + Task quality
   `Approved/Needs-fixes`) to `.ui-forge/review.md`, severity Critical/Important/Minor. Resolve any
   **⚠️ cannot-verify** item yourself. Any `❌` or unresolved `⚠️` → fix pass → re-run Stage 1. Do NOT
   run the browser until both verdicts are clean. Never pre-judge findings in the dispatch.
3. **Stage 2 — visual review** — ensure the app is running (use the run command context.md recorded;
   if none, ask the user to start it and give the URL). Dispatch `design-reviewer` (Sonnet +
   Playwright). It screenshots @ desktop/tablet/mobile × light/dark, checks a11y/anti-patterns/console
   → verdict `PASS | NEEDS-ITERATION` (triage [Blocker]/[High]/[Medium]/Nit).
   - `NEEDS-ITERATION` → feed Blockers/High-Priority back to `ui-implementer`, re-run from Stage 1.
   - `BLOCKED` (app unreachable) → surface to the user; **do not fake a pass**.
   - `DEGRADED` (non-browser stack, no web preview — native mobile/desktop) → the static phases ran but
     the render was unseen. **Do not claim visual done.** Surface to the user the exact screens ×
     viewports × themes to screenshot for manual sign-off; record it as a `⚠️` on the Step-5 checklist.
4. After a clean round, append to `.ui-forge/progress.md`: `Task: complete (commits <base7>..<head7>,
   spec✅ visual✅)`.

If Blockers remain after ~3 rounds → **stop and report** what couldn't be resolved.

### Step 4.5 — FINAL WHOLE-CHANGE REVIEW (Opus)
Dispatch ONE final review on the **most capable model** over the whole change diff, using
`review-rubric.md`'s final section (plan alignment, code quality, architecture, testing, production
readiness incl. migration/backward-compat if backend touched). Verdict **Ready? Yes|No|With fixes**.
Findings → ONE consolidated fix dispatch.

### Step 5 — VERIFY-BEFORE-DONE GATE (you, Opus)
**Iron Law:** NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE. No "should work / looks good /
done!" before the proof exists in this turn.

**Gate Function (superpowers) — run this loop for every claim below; skipping a step is lying, not
verifying:**
1. **IDENTIFY** — for each checklist item, name the exact command / artifact that *proves* it (the
   screenshot file, the console dump, the `git diff BASE..HEAD`, the endpoint run, the a11y snapshot).
2. **RUN** — execute it **fresh, in this turn, in full** — not from memory, not a cached result, not a
   subagent's summary. Reviewers are read-only; you confirm their evidence exists.
3. **READ** — actually read the output: exit code, error/warning count, the screenshot, the verdict
   line. Do not skim.
4. **VERIFY** — the output must actually satisfy the item (zero Blockers/High, contrast passes, diff
   shows the change, run is green). A partial or ambiguous result is a FAIL, not a pass.
5. **ONLY THEN** check the box. Any unproven item blocks "done".

**Common false-passes to catch:** a subagent *reporting* success while the diff shows no change; a PASS
verdict with no screenshot actually on disk; "dark mode fine" never toggled; an endpoint "added" that
was never curled. Treat each as unverified until step 2–4 close it.

Confirm each with evidence:
- [ ] Clarified intent + approved direction matched; scope minimal
- [ ] Compliant with the project design system (tokens/components), or the newly-established one
- [ ] Stage-1: Spec ✅ + Task quality Approved; ⚠️ items resolved
- [ ] Stage-2: screenshots **actually taken** @ desktop+tablet+mobile, light+dark
- [ ] Step 4.5 final review = Ready / fixes applied
- [ ] A11y pass + zero console errors (verified live)
- [ ] Existing components/tokens reused; no duplication
- [ ] Backend contract intact & backward-compatible, verified by a real run (if touched)
- [ ] Information shown in the richest fitting form, not defaulted to plaintext
- [ ] Ledger updated

Then report: what changed, the review route + screenshots, and anything flagged.

---

## Model routing
- **Opus** — orchestrator, clarify/brainstorm gate, `ui-strategist`, Step-4.5 final review, Step-5 gate.
- **Sonnet** — `ui-context-manager`, `ui-implementer`, `backend-integrator`, both per-task reviewers.
- **Nuance:** *turn count beats token price* — a too-cheap model that takes 2–3× the turns costs more.
  Sonnet is the floor for reviewers and prose-driven implementers; drop to cheapest tier only when the
  brief contains the exact code to transcribe.
- **Always name the model explicitly** when dispatching — an omitted model inherits the (often most
  expensive) session default. Any agent `BLOCKED` on reasoning complexity → re-dispatch on Opus.

## Worked example (illustrative, stack-neutral)
```
User: "Show the search results better."
Step 0  Ambiguous (which screen? what does 'better' mean? current form?). Ask:
        Q1 Which screen — results list or detail? Q2 What's wrong now (density? scannability?)
        Q3 direction: [A ranked cards w/ score meters] [B comparison bar-chart] [C data table]
        User picks A. Direction approved.
Step 1  context-manager: stack = <detected>; design system = <detected DS or none>; run cmd =
        <detected>; API returns results[] with {title, score, snippet, source}. → context.md
Step 2  strategist: register = <derived from product>; dials var/mot/den; components: ResultCard
        (reuse existing Card), ScoreMeter (new, per component-patterns.md), presentation = ranked
        cards + meters (chart-catalog: meter for a 0–1 confidence). data: all HAVE. → brief.md
Step 3  (skipped — no NEED fields)
Step 4  implementer builds → report.md → spec-review (Spec ✅, Quality Approved) → visual-review
        screenshots 3 viewports + dark: [High] meter invisible in dark mode → fix → PASS.
Step 4.5 final review: Ready.
Step 5  Iron-Law checklist passes → report with screenshots.
```

## Red flags — STOP and correct
- **Never** skip Step 0; never guess to avoid a question.
- **Never** ship blind — no running app / no Playwright → tell the user how to enable it; don't fake PASS.
- **Never** run the browser (Stage 2) before Stage 1's two verdicts are clean.
- **Never** fabricate data — integrate it (Step 3) or re-clarify.
- **Never** override the project's existing design system with your own taste — obey it; propose changes
  to it explicitly if needed.
- **Never** paste session history into a dispatch — hand file paths; keep context lean.
- **Never** pre-judge a reviewer's findings ("treat as minor", "don't flag X").
- **Never** claim done without the Step-5 evidence.

## Prerequisites
- Playwright MCP configured in `.mcp.json` (approve on first prompt / `claude mcp`).
- The app runnable locally for Stage-2 review (context.md records the command; else ask the user).
- `.ui-forge/` is created at runtime — add it to the project's ignore file.

## Reference index
`references/` — `design-system-discovery.md`, `style-registers.md`, `ux-guidelines.md`,
`chart-catalog.md`, `component-patterns.md`, `anti-patterns.md`, `handshake-protocol.md`,
`review-rubric.md`, `clarify-gate.md`, `dispatch-templates.md`.
