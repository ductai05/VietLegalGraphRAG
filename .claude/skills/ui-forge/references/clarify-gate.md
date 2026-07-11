# Clarify / Brainstorm Gate — ask before build (project-agnostic)

Modeled on **obra/superpowers** `brainstorming`. The #1 rule of ui-forge: **resolve ambiguity and get a
design direction approved before writing any code.** A hallucinated guess costs a full build+review
loop; a question costs one message. Do not guess to seem helpful. This is the single most important
defense against wasted work.

---

## The hard gate (superpowers brainstorming)
> Do NOT invoke any implementation step, write any code, or dispatch the builder until you have
> presented a design direction and the user has approved it.

This applies **even to changes that look trivial** — but *the weight of the gate scales with the
ambiguity*, it is not a fixed ritual. The gate has two jobs:
1. **Resolve ambiguity** — you know exactly what to build and where.
2. **Get a direction approved** — the user has blessed an approach before the strategist writes the
   full brief, so you never build the wrong thing well.

**What "approval" means scales (see Ambiguity triage below).** For a genuinely open visual/UX approach
it means 2–3 alternatives chosen from. For a fully-specified, low-ambiguity change the design system
already answers, it means a **single lightweight confirm** ("darkening `primary` to the brand's deeper
blue token, buttons only — go?") — never a manufactured 2–3-way choice. Over-asking on an unambiguous
request is as real a failure as under-asking on a vague one. The invariant that never bends: **no
product code is written until intent is confirmed** — the confirm can be one line, but it must exist.

## Ambiguity triage — size the gate to the request (do this first)
Classify the request before asking anything. This prevents both failure modes (under-asking on vague,
over-asking on clear).

| Tier | Signal | Gate weight | Directions? |
|------|--------|-------------|-------------|
| **A — Low** | Every noun maps to one screen/component; the change is one well-defined property or a copy edit; the design system already dictates the answer (color/spacing/type token); data all HAVE. | **Fast-path:** 0–1 decisive question (e.g. exact token/hex), then a **one-line confirm**. Skip alternatives. | No |
| **B — Medium** | Target clear but the *form* or *scope* has a few reasonable options; some data may be NEED; visual approach partly open. | 1–3 questions + **1 recommended direction** stated for confirm (offer alternatives only if the user pushes back). | Optional |
| **C — High** | Vague intent ("better", "more suitable"), multiple screens, register shift, new components, or undefined/derived data. | Full gate: batched questions (loop) + **2–3 alternative directions** with `preview` trade-offs. | Yes |

Fast-path (Tier A) still obeys the invariant — one confirm line before code — it just does not
manufacture choices the request already settled. When unsure between tiers, round **up** one tier.

## Gate procedure
1. **Explore context first** — read `.ui-forge/context.md` (or, if not booted yet, do a quick scan)
   so questions are informed, not lazy. Map each noun in the request to a real screen/component/field.
2. **Ask clarifying questions** (taxonomy below) with `AskUserQuestion` — concrete options, recommended
   one first, one-line rationale each. Ask the few decisive questions at once (max 4), not a slow drip.
3. **Present 2–3 alternative directions** with trade-offs when the visual/UX approach is genuinely open
   (e.g. "results as ranked cards with score meters" vs "as a comparison bar chart" vs "as a data
   table"). Use `preview` mockups. Recommend one and say why.
4. **Incremental approval** — for a larger change, present the direction in sections and confirm each,
   rather than one giant proposal the user must accept or reject wholesale.
5. **Scope review before leaving** — restate what's in and explicitly out of scope; watch for
   placeholders, contradictions, and remaining ambiguity. Only then proceed to the strategist (Step 2).

## Ambiguity taxonomy — ask when any of these is unresolved
| Type | Ambiguous signal | Example to clarify |
|------|------------------|--------------------|
| **Target** | which screen/route/component? | "on the site" — landing or the app view? which component? |
| **Data** | what exact information, from where? | "show stats" — which metrics? per item or aggregate? source? |
| **Presentation** | how should it look/behave? | "add a chart" — of what? bar/line/graph? (offer directions) |
| **Scope** | how much / boundary? | "improve the results area" — restyle only, or add features? |
| **Intent/priority** | why / what matters most? | speed vs completeness vs visual impact? |
| **Trigger** | user action or automatic? | on click, on load, on hover, on scroll? |
| **State** | empty/loading/error handling? | what shows before data arrives / when none / on failure? |
| **Register shift** | does this change the product's look? | "make it playful" on a serious app — confirm intent |
| **Constraints** | any hard limits? | timeline, no new deps, must match an existing screen, i18n? |

## Safe to assume (don't over-ask)
- Anything already codified in the project's design system (colors, type, spacing, radius) — obey it.
- Established conventions in the existing codebase (language of UI copy, layout patterns, naming).
- Reasonable, reversible defaults where the user clearly doesn't care — **state the assumption and move
  on** rather than blocking on a trivial choice.

## Anti-hallucination checks before leaving the gate
All three must be true — else ask, don't proceed:
1. Every noun in the request maps to a real screen/component/field you can point to.
2. You know the data source for every value to be displayed (HAVE now, or backend-integrator will add it).
3. You know which files will change and roughly the diff size, and a direction is approved.

## How to ask well
- Options over open questions: give 2–4 concrete choices, not "what do you want?".
- Lead with your recommendation, labeled "(Recommended)", with a one-line reason.
- Use `preview` mockups (ASCII/markdown) for visual/layout trade-offs so the user can compare.
- **Loop:** if answers open new ambiguity, ask again. Exit only when the request is concrete + bounded +
  a direction is approved.

## What NOT to do
- Don't proceed on "probably means…". Don't invent data, screens, or scope to avoid a question.
- Don't ask about things the design system already answers. Don't drip one question per message.
- Don't skip direction approval because the change "seems small".
