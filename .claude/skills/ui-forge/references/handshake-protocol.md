# Handshake Protocol, File Handoffs & Progress Ledger (project-agnostic)

Adapted from **VoltAgent** (context handshake) + **obra/superpowers** (file handoffs, progress ledger,
status returns, model-by-complexity). This is how the orchestrator and subagents coordinate **without
bloating each other's context windows**. Nothing here depends on a framework or language.

---

## 1. The `.ui-forge/` workspace (created at runtime)
The orchestrator creates a working directory at the repo root. Agents read/write **files**; the
orchestrator passes **paths**, never pasted history. Add `.ui-forge/` to the project's ignore file.

```
.ui-forge/
  context.md        # ui-context-manager: stack, design system, run command, API surface
  design-system.md  # (only if none existed) the established token system — authoritative thereafter
  brief.md          # ui-strategist: the Build Brief (register, dials, components, data contract)
  report.md         # ui-implementer: what changed, files, reuse notes, review route, self-review
  review.md         # design-spec-reviewer + design-reviewer: verdicts + findings (append per round)
  progress.md       # the LEDGER — append-only, survives context compaction
```

Why files: everything you paste into a dispatch — and everything a subagent prints back — stays
resident in your context for the rest of the session and is re-read every turn. Files keep it lean.

## 2. Context handshake (VoltAgent)
On start, each subagent states what context it needs. If `context.md` exists it reads that **first** and
only asks the orchestrator for genuinely missing, mission-critical details. Conceptual opening query
(agents phrase it in their report, not as literal JSON unless useful):

```json
{ "requesting_agent": "<name>",
  "request_type": "get_project_context | get_design_context",
  "payload": { "query": "<the specific facts this agent needs>" } }
```

Mid-task progress (keep short, optional):
```json
{ "agent": "<name>", "update_type": "progress", "completed": ["..."], "next": ["..."] }
```

## 3. Status returns (superpowers) — how a subagent ends its turn
Every agent ends with exactly ONE status. The orchestrator acts on it:

| Status | Meaning | Orchestrator action |
|--------|---------|---------------------|
| `DONE` | finished, self-checked | proceed / dispatch the next stage |
| `DONE_WITH_CONCERNS` | done but flagged doubts (e.g. a file grew large, a risk) | read concerns; if correctness/scope, address before proceeding; if observation, note + proceed |
| `NEEDS_CONTEXT` | missing info to continue | supply it, re-dispatch the **same** agent/model |
| `BLOCKED` | cannot proceed | diagnose: **context** → re-dispatch with info; **reasoning complexity** → upgrade the model (→ Opus); **task too large** → split; **scope/plan error** → escalate to Step 0 clarify |
| `DEGRADED` | did the verifiable part; something couldn't be verified in this environment (e.g. non-browser stack has no web preview for the visual review) | record what ran vs what didn't; surface the manual step to the user; **never upgrade it to a silent pass** |

Never ignore an escalation or force the same model to retry unchanged. If the subagent said it's stuck,
something must change.

## 4. File handoffs (superpowers) — what goes where
- **Task brief:** the orchestrator points the implementer at `brief.md` ("read this first — your
  requirements"). Exact values live only in the brief.
- **Report file:** the implementer writes the full report to `report.md`; returns only status, changed
  files, review route, and a one-line result (< ~15 lines back to the orchestrator).
- **Reviewer inputs = 3 paths, never pasted diffs:** the same `brief.md`, the `report.md`, and the diff.
  Record the BASE commit before dispatching the implementer; the diff is `git diff BASE..HEAD` — **never
  `HEAD~1`**, which drops all but the last commit of a multi-commit change. Also hand the reviewer the
  brief's binding constraints verbatim.
- **Fix dispatches** append their fix report (with any check results) to `report.md`; re-reviews read the
  updated file.

## 5. ⚠️ Cannot-verify-from-diff (superpowers)
A reviewer may report "⚠️ cannot verify from diff" — a requirement that lives in unchanged code or spans
the change. These don't block the rest of the review, but the **orchestrator must resolve each one**
(it holds the cross-task context the reviewer lacks). Confirm against the brief; a real gap = failed
spec review → back to the implementer. Never leave a ⚠️ unresolved at the done gate.

## 6. Durable progress — the ledger (superpowers)
Conversation memory does not survive compaction. Track progress in `progress.md`, not only todos.
- At skill start, `cat .ui-forge/progress.md`. Tasks listed complete are DONE — don't re-dispatch;
  resume at the first not marked complete.
- After a clean review round, append one line:
  `Task: complete (commits <base7>..<head7>, spec✅ visual✅)`.
- The commits it names exist in git even after compaction — trust the ledger + `git log` over memory.

## 7. Model-by-complexity dispatch (superpowers)
- Name the model explicitly on every dispatch — omission inherits the (often most expensive) session
  default.
- *Turn count beats token price:* a too-cheap model that takes 2–3× the turns costs more. Sonnet is the
  floor for reviewers and prose-driven implementers; cheapest tier only for exact-code transcription.
- Judgment/design/final-review → Opus. Mechanical build/review → Sonnet.

## 8. Bias-free dispatch rules
- **Never pre-judge findings** in a reviewer dispatch ("treat X as minor", "don't flag Y", "the brief
  chose Z"). Let the reviewer raise it; adjudicate in the loop.
- **Never paste session history** ("state after tasks 1–3") into a dispatch. A fresh subagent needs its
  task (brief path), the interfaces it touches, and the constraints — nothing else.
- **Reviewers are read-only** on the checkout — they must not mutate the working tree, index, or HEAD.

## 9. Recovery after compaction
On resume: read `context.md`, `brief.md`, and `progress.md`; run `git log --oneline` for the range.
Reconcile what the ledger says is done against git, then continue at the first incomplete task. Do not
re-run completed tasks.
