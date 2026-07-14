# ui-forge — Project-Agnostic Multi-Agent UI Workflow

> A reusable Claude Code workflow that makes UI/UX changes come out **visually strong and design-system-
> compliant without manual re-prompting**, in **any** frontend stack. Drop the `.claude/` skill + agents
> into a project and it discovers the stack, discovers or establishes the design system, clarifies
> ambiguity, decides a context-aware design, implements it, and **verifies the render with real-browser
> screenshots** in a loop. Opus decides, Sonnet builds.

It is **not** built from scratch — every mechanism maps to a battle-tested, high-star repo (§1). It is
also **not** hardcoded to any project — all project specifics are discovered at runtime (§4).

---

## 1. Reference repositories (read from source, adapted — not copied)

| Repo | Scale | What we take |
|------|-------|--------------|
| **obra/superpowers** ([gh](https://github.com/obra/superpowers)) | large, actively-maintained skill suite (star count not independently verified) | Orchestration spine: `subagent-driven-development` (pre-flight scan → per-task loop → **two-verdict review** → fix-loop → **progress ledger**), `brainstorming` (hard gate: no code until a direction is approved; 2–3 alternatives), `verification-before-completion` (Iron Law), file-handoffs, model-by-complexity, status returns. Its `SKILL.md` is **21,647 bytes**; `task-reviewer-prompt.md` 7,919; `implementer-prompt.md` 5,522; `code-reviewer.md` 5,213. |
| **nextlevelbuilder/ui-ux-pro-max-skill** ([gh](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)) | large CSV-backed design knowledge base (star count not independently verified) | Design-intelligence engine: reasoning-rules (product→register), **design dials** `--variance/--motion/--density` (ranges verbatim), 50+ styles / **161 palettes** / 57 fonts / **99 UX guidelines** / **25 chart types**, **3-tier anti-pattern validation**. It's a whole ecosystem — many SKILLs (design, design-system, ui-styling, brand…) each 7–12KB **plus large CSV databases** (e.g. `logo/styles.csv` 13.7KB, `cip/deliverables.csv` 13.4KB) and a 24.5KB `quick-reference.md`. |
| **VoltAgent/awesome-claude-code-subagents** ([gh](https://github.com/VoltAgent/awesome-claude-code-subagents)) | 100+ subagents | **context-manager handshake** (JSON `get_project_context`, 3-phase discovery→execution→handoff, agent-integration map), `frontend-developer` / `ui-designer` agent format. |
| **OneRedOak/claude-code-workflows → design-review** ([gh](https://github.com/OneRedOak/claude-code-workflows/tree/main/design-review)) | published design-review workflow (star count not independently verified) | Visual review agent: **8 phases** (0–7, incl. Robustness), `[Blocker]/[High-Priority]/[Medium-Priority]/Nit`, Playwright, 3 viewports. |
| **ap7i — "Giving Claude Code Eyes with Playwright MCP"** ([post](https://ap7i.com/posts/giving-claude-code-eyes-with-playwright-mcp/)) | — | The autonomous **see→fix loop** — the core fix for "the agent can't tell if the UI is good." |

**Consensus shape:** `clarify/approve → design-intelligence → implement → SEE it → two-stage review loop
→ verify → done`, coordinated through a **context broker + file handoffs + a progress ledger**.

## 2. Source fidelity (how the references were read)
Read directly from `raw.githubusercontent.com` and reproduced **verbatim where the fetch allowed**, then
**adapted** to be project-agnostic (not copied — copying their React/Tailwind/logo/slide content would be
wrong for arbitrary projects). Fidelity is **not uniform across sources** — it is what it is, per mechanism:
- **Full-depth (mechanism + branching reproduced):** superpowers `subagent-driven-development`,
  `verification-before-completion` (incl. the IDENTIFY/RUN/READ/VERIFY gate function),
  `implementer-prompt`, `task-reviewer-prompt`, `code-reviewer` (adapted: TDD/test-suite mechanics
  dropped, no suite in this flow); OneRedOak `design-review-agent` (8 phases w/ per-phase checks);
  ap7i see→fix discipline; ui-ux-pro-max **design dials** (verbatim 1–10 ranges) and **chart catalog**
  (~25 forms w/ selection criteria).
- **Deliberate divergence:** superpowers `brainstorming` "one question at a time" is inverted to
  batched ≤4 questions (driven by `AskUserQuestion`); the clarify gate is tiered (A/B/C) so it scales
  to ambiguity instead of always presenting alternatives.
- **Distilled, not exhaustive (by design — full CSV breadth would bloat context):** ui-ux-pro-max's
  reasoning engine and style taxonomy. `style-registers.md` reproduces the register-classification,
  the **conditional Decision_Rules branching**, and per-family style specs across a broad set of
  domains — a working engine, not the raw 193-product / 85-style databases row-for-row. The 3-tier
  anti-pattern framing is a local reorganization of the source's 10-priority/severity model.
- **Reinterpreted:** VoltAgent context-manager — the handshake JSON + a 3-phase operating protocol +
  an agent-integration map are reproduced in `ui-context-manager.md` / `handshake-protocol.md`,
  adapted to this pipeline's file-handoff model.
Star counts in §1 were not independently verified — treat them as "notable/large", not exact.

## 3. What makes it good (design principles)
1. **Project-agnostic** — no framework/language/backend/design-system is assumed; all discovered at
   runtime (`references/design-system-discovery.md`). Obeys an existing design system; establishes a
   minimal one if none.
2. **See before done** — no UI is called finished without a real-browser screenshot.
3. **Ask before build** — ambiguity resolved and a direction approved up front (hard gate).
4. **Separation of concerns** — 6 focused agents, each in clean context, communicating via files.
5. **Evidence over assertion** — "done" needs fresh proof (Iron Law).
6. **Context stays lean** — context broker + file handoffs + ledger keep cold subagents cheap and
   compaction-safe.

## 4. Architecture

```
UI/UX request (any stack)
   │
   ▼ Step 0  CLARIFY/BRAINSTORM GATE (Opus) — ask + present 2–3 directions + approve  → no code until approved
   ▼ Step 1  ui-context-manager (Sonnet) — discover stack + design system + RUN cmd + API → .ui-forge/context.md
   ▼ Step 2  ui-strategist (Opus) — register + dials + viz-first brief; obey or establish design system → brief.md
   ▼ Step 3  backend-integrator (Sonnet) — additive, framework-detected  [only if brief NEEDs data]
   ▼ Step 4  LOOP: ui-implementer → design-spec-reviewer (static, 2 verdicts) → design-reviewer (Playwright visual) → fix
   ▼ Step 4.5 final whole-change review (Opus)
   ▼ Step 5  VERIFY-BEFORE-DONE gate (Opus, Iron Law) → report + screenshots
```

### Files
```
.mcp.json                                   # Playwright MCP (the eyes)
.claude/agents/                             # 6 subagents, stack-agnostic
    ui-context-manager.md   Sonnet   discover project + write context.md
    ui-strategist.md        Opus     design-intelligence brief
    backend-integrator.md   Sonnet   additive backend (any framework)
    ui-implementer.md       Sonnet   build in the project's stack
    design-spec-reviewer.md Sonnet   Stage-1 static (spec + quality, 2 verdicts)
    design-reviewer.md      Sonnet+Playwright  Stage-2 visual loop
.claude/skills/ui-forge/
    SKILL.md                orchestration spine (decision tree, worked example, red flags)
    references/
        design-system-discovery.md   # detect stack + design system; establish one if none
        style-registers.md           # domain→register reasoning rules + dials + families
        ux-guidelines.md             # enumerated 10-priority UX/a11y ruleset
        chart-catalog.md             # viz-first: data-shape→form, 25+ forms, specs
        component-patterns.md        # component anatomy + required states + a11y
        anti-patterns.md             # 3-tier validation + outstanding test
        handshake-protocol.md        # .ui-forge/ workspace, handoffs, status codes, ledger
        review-rubric.md             # two-stage severity + verdicts + do-not-trust + ⚠️ + final review
        clarify-gate.md              # brainstorm hard-gate, ambiguity taxonomy, direction approval
        dispatch-templates.md        # fill-in prompt template per agent
.ui-forge/                                   # runtime workspace (gitignored)
    context.md  design-system.md(if new)  brief.md  report.md  review.md  progress.md(ledger)
```

## 5. Requirements the workflow satisfies
Original goals: **R1** context-aware styling · **R2** viz-first, outstanding output · **R3** clean
backend integration · **R4** ambiguity gate / no hallucination. Added: **R5** design-system fidelity ·
**R6** visual verification loop · **R7** a11y (WCAG AA) + responsive · **R8** scope discipline · **R9**
reuse · **R10** model routing · **R11** performance budget · **R12** dark-mode parity · **R13**
reversible/contract-safe backend · **R14** two-stage + final review · **R15** shared context broker ·
**R16** file handoffs + ledger · **R17** anti-pattern validation · **R18** verify-before-done ·
**R19 (new)** project-agnostic discovery/establishment of stack + design system.

## 6. Using it in any project
1. Copy `.claude/skills/ui-forge/`, `.claude/agents/`, and `.mcp.json` into the target repo.
2. Approve the Playwright MCP on first run (or `claude mcp`).
3. Ensure the app can run locally (the context-manager detects the command; else it asks).
4. Add `.ui-forge/` to the ignore file.
5. Invoke `/ui-forge <request>` — or just describe a UI change (auto-triggers).

Sources: [superpowers](https://github.com/obra/superpowers) · [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) · [VoltAgent](https://github.com/VoltAgent/awesome-claude-code-subagents) · [OneRedOak](https://github.com/OneRedOak/claude-code-workflows/tree/main/design-review) · [Playwright eyes](https://ap7i.com/posts/giving-claude-code-eyes-with-playwright-mcp/)
</content>
