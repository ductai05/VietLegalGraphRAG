# Design-System Discovery & Establishment (project-agnostic)

The whole workflow adapts to the project instead of assuming one. This file tells the
**ui-context-manager** how to detect the stack and design system, and tells the **ui-strategist** how
to establish a lightweight design system when none exists. Everything downstream (brief, build,
review) references what this step records — never hardcoded framework/token names.

---

## 1. Detect the stack (context-manager)

Look for signals; record what you find, mark unknowns as unknown (never guess):

| Layer | Where to look | What to record |
|-------|---------------|----------------|
| Package manager / lang | `package.json`, `pnpm-lock`, `deno.json`, `pubspec.yaml`, `Gemfile`, `*.csproj`, `go.mod` | language(s), package manager |
| Frontend framework | deps + file extensions: `react`/`.tsx`, `vue`/`.vue`, `svelte`/`.svelte`, `@angular/*`, `astro`, `solid-js`, `lit`, SwiftUI/`.swift`, Flutter/`.dart`, or plain `.html/.css/.js` | framework + version |
| Styling system | `tailwind.config.*`, CSS Modules, `styled-components`/`emotion`, SCSS, vanilla CSS, CSS custom properties, `unocss` | styling approach |
| Component library | `@mui/*`, `@chakra-ui/*`, `antd`, `@shadcn`/`components/ui`, `@mantine/*`, `bootstrap`, Radix, Headless UI, native | library + where components live |
| Build / dev server | `vite`, `next`, `nuxt`, `webpack`, `parcel`, framework CLIs; scripts in `package.json` | **the exact command to run the app locally**, and the URL/port |
| Routing / pages | router config, `pages/`, `app/`, `routes/`, `.html` files | route → screen map |
| Backend (if any) | `src/backend`, `server/`, `api/`, framework deps (Express/Fastify/FastAPI/Rails/Spring/…) | backend framework + how the FE calls it |
| Test / lint | test runner, eslint/stylelint/biome, formatter | commands to verify |

**Output:** the "Stack" section of `context.md`, including the single most important line for review:
`RUN: <command> → <url>` (how Stage-2 opens the app). If you cannot determine it, say so — the
orchestrator will ask the user.

---

## 2. Detect the design system (context-manager)

A "design system" here = the source of truth for colors, typography, spacing, radius, elevation,
motion, and component styling. It may be explicit or implicit. Search in this order and record the
**first** authoritative source found:

1. **Explicit token files** — `tailwind.config.*` theme, CSS custom properties (`:root { --… }`),
   `theme.ts/js`, design-token JSON (Style Dictionary, `tokens.json`), SCSS variable files,
   `*.stories.*` / Storybook theme, a `DESIGN.md`/`STYLEGUIDE.md`/`design-principles.md`, a Figma
   token export.
2. **Component library defaults** — if MUI/Chakra/Ant/shadcn etc. is present, its theme config +
   documented conventions are the system.
3. **Implicit conventions** — if none of the above, infer the *de facto* system by sampling existing
   screens: recurring colors, font families/sizes, spacing rhythm, border-radius, whether shadows are
   used, light/dark handling.

Record in `context.md` under "Design system":
- Source of truth (file path or "implicit — inferred").
- **Token inventory:** color roles (bg/surface/text/border/brand/status), type scale, spacing scale,
  radius scale, elevation/shadow policy, motion durations/easing, breakpoints.
- **Component inventory:** existing reusable components/classes by name + where defined (so the
  implementer reuses, never duplicates).
- **Light/dark mechanism:** how theme switches (CSS media query, `data-theme`, class, context provider).
- **Compliance rules** the project already enforces (e.g. "no raw hex", "8px grid", "pill buttons").
- **Maturity:** `mature` (obey strictly) · `partial` (obey + fill gaps) · `none` (establish one).

---

## 3. Establish a design system when none exists (strategist)

If maturity = `none` or `partial`, the strategist proposes the minimum viable system for the register
(see `style-registers.md`) and records it to `.ui-forge/design-system.md` so every future run is
consistent. Keep it small but complete:

- **Color roles** (not raw values scattered in code): `bg`, `surface`, `surface-alt`, `text`,
  `text-muted`, `border`, `brand`, plus `success/warning/danger/info`. Provide light + dark values.
  Prefer defining them as tokens in the project's native mechanism (CSS custom properties, Tailwind
  theme, etc.) — match the stack detected in §1.
- **Type scale** — family(ies) + a modular scale (e.g. 12/14/16/18/24/32/40/48) with weights and
  line-heights; a body default (16px/1.5) and heading tracking.
- **Spacing scale** — a base unit (4 or 8px) and multiples; container widths; section rhythm.
- **Radius scale**, **elevation policy** (shadows vs flat), **motion** (durations 150–300ms + easing),
  **breakpoints** (mobile-first).
- **Accessibility floor** — contrast ≥ 4.5:1 body / 3:1 large, visible focus, reduced-motion honored.

**Rule:** establishing a system is a design decision — surface the proposed tokens in the brief and,
for a from-scratch system, get user sign-off in Step 0's direction approval. Once recorded, treat
`design-system.md` as authoritative for subsequent runs (obey, don't reinvent).

---

## 4. How downstream steps reference this
- **brief.md** names token *roles* and existing components, never raw values or foreign framework names.
- **ui-implementer** maps roles → the project's native tokens (the mechanism recorded in §2).
- **reviewers** check against the recorded system (mature → strict; established → the new file).
- If the design system is ambiguous or contradicts itself, that is a Step-0 clarify item, not a guess.
