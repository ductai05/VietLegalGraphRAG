# Style Registers — reasoning rules, register profiles & design dials (project-agnostic)

Adapted from **ui-ux-pro-max**'s reasoning-rules engine (product/domain → register → style). The strategist
maps the product to a visual *register*, sets the *design dials*, runs the *conditional reasoning engine*
to adjust them, picks a compatible *style family*, then expresses everything in the project's own design
tokens (discovered or established per `design-system-discovery.md`). **If the project has a mature design
system, it wins on concrete tokens** — the register only guides judgment calls the system leaves open
(which viz, how much motion, layout emphasis, imagery, density-per-screen).

**Project-agnostic discipline.** Nothing below names a framework, a component library, or a raw value
(no hex, no px-as-literal-token, no utility classes). Colors are **token ROLES** ("trust-accent",
"status-alert", "surface-base"), spacing is a **step on the project's scale**, and px figures are
*guidance to map onto that scale* — never emitted as literals. The strategist translates every role into
the project's actual token before it reaches the brief.

---

## 1. How to derive the register (in order)
1. **Product type** — classify into one of five parent families: **Entertainment** (social, video, music,
   gaming, streaming), **Tool** (scanner, editor, converter, AI assistant, search), **Productivity**
   (task/notes/calendar/project), **Service** (health, beauty, finance, real-estate, booking), **Hybrid**
   (commerce + social, SaaS + content). The parent family biases style, color mood, type mood, layout.
2. **Domain / industry** — narrow within the family (legal, gov, finance, health, kids, dev-tools,
   analytics, luxury, gaming, crypto, etc.). Domain sets formality and trust requirements.
3. **Audience & context** — expertise level, device, environment (professional focus vs casual leisure),
   emotional need (trust vs delight vs speed vs calm).
4. **Explicit keywords** in the request ("minimal", "playful", "dark", "premium", "dense") override
   defaults. A keyword that fights the existing system is a **Step-0 clarify** (see §4, `if_keyword_conflict`).
5. **Existing system** — if the project already has a look, the register must *cohere* with it, not fight
   it. A restyle changes the system deliberately, not accidentally.

## 2. Register profiles — product/domain → register + dials
~35 representative clusters generalizing the source's 193 product types. **Register** = the felt tone.
**Formality**: Formal / Semi-formal / Casual / Expressive. **Dials** = variance / motion / density (1–10,
defined in §3). Ranges are a starting point; §4 adjusts them, and dials are tuned **per screen** (a
reading view goes spacious even inside a dense product).

| Product / domain cluster | Register | Formality | var / mot / den |
|--------------------------|----------|-----------|-----------------|
| Legal / law firm / compliance | authoritative, restrained, credential-forward | Formal | 2–3 / 2–4 / 4–6 |
| Government / public / civic services | institutional, accessible, plain | Formal | 1–3 / 1–3 / 4–6 |
| Banking / traditional finance | secure, sober, trustworthy | Formal | 2–4 / 2–4 / 5–7 |
| Fintech / crypto / web3 | modern-secure, dark-tech, precise | Semi-formal | 4–6 / 3–5 / 6–8 |
| Insurance | reassuring, clear, comparison-driven | Formal | 2–4 / 2–4 / 4–6 |
| Healthcare / medical / clinical | calm, precise, accessible | Formal | 2–4 / 3–5 / 4–6 |
| Mental health / meditation / wellness | gentle, calming, private | Semi-formal | 3–5 / 3–5 / 2–4 |
| Fitness / sport / activity tracking | energetic, motivating | Casual | 6–8 / 6–8 / 4–6 |
| Kids / early-education / family-safe | playful, warm, safe | Expressive | 6–8 / 6–9 / 2–3 |
| Education / e-learning / courses | engaging, structured, encouraging | Semi-formal | 5–7 / 5–7 / 3–5 |
| Docs / knowledge base / dev docs | legible, scannable, neutral | Semi-formal | 2–3 / 1–3 / 5–7 |
| Developer tools / CLI / API / technical | efficient, dense, dark-first | Semi-formal | 3–5 / 2–4 / 7–9 |
| Analytics / BI / data dashboard | legible, dense, scannable | Semi-formal | 3–5 / 2–4 / 7–9 |
| Enterprise admin / internal ops tools | functional, consistent, sober | Formal | 2–4 / 2–4 / 6–8 |
| Productivity / SaaS (general) | clean, efficient, confident | Semi-formal | 3–6 / 3–5 / 5–7 |
| AI chat / assistant / conversational | minimal, responsive, focused | Semi-formal | 3–5 / 3–5 / 3–5 |
| E-commerce / retail / marketplace | desirable, clear, conversion-focused | Casual | 4–6 / 4–6 / 4–6 |
| Luxury / premium brand / high-end retail | elegant, spacious, refined | Semi-formal | 4–6 / 3–5 / 2–3 |
| Marketing / landing / campaign | persuasive, bold, memorable | Casual | 5–8 / 5–8 / 2–4 |
| Creative agency / portfolio / studio | expressive, differentiating, wow | Expressive | 7–10 / 6–9 / 3–5 |
| Social / community / messaging | vibrant, engaging, lively | Casual | 6–8 / 6–8 / 4–6 |
| Media / streaming (video / music / podcast) | immersive, content-first, dark | Casual | 5–7 / 6–8 / 5–7 |
| News / editorial / publishing / long-form | legible, hierarchical, sober | Semi-formal | 3–5 / 2–4 / 4–6 |
| Gaming / immersive / entertainment | immersive, high-energy | Expressive | 7–10 / 8–10 / 4–7 |
| Booking / travel / hospitality / hotel | inviting, trustworthy, aspirational | Casual | 4–6 / 4–6 / 4–6 |
| Food delivery / restaurant / dining | appetizing, warm, fast | Casual | 5–7 / 5–7 / 3–5 |
| Real estate / property | aspirational, clear, media-rich | Semi-formal | 4–6 / 4–6 / 4–6 |
| Logistics / delivery / tracking / fleet | functional, real-time, glanceable | Semi-formal | 3–5 / 3–5 / 6–8 |
| Notes / writing / reading (distraction-free) | calm, minimal, paper-like | Semi-formal | 1–3 / 1–3 / 3–5 |
| Nonprofit / charity / cause / civic-impact | emotive, transparent, trustworthy | Semi-formal | 4–6 / 4–6 / 3–5 |
| Beauty / spa / salon | calm, refined, tactile | Semi-formal | 3–5 / 3–5 / 2–4 |
| Automotive / vehicle | precise, aspirational, spec-driven | Semi-formal | 4–6 / 4–6 / 4–6 |
| IoT / smart home / hardware dashboard | real-time, glanceable, dark | Semi-formal | 4–6 / 3–5 / 6–8 |
| Cybersecurity / security ops | dark, technical, alert-driven | Semi-formal | 4–6 / 3–5 / 7–9 |
| Sustainability / climate / eco tech | organic, transparent, earthy | Semi-formal | 4–6 / 3–5 / 4–6 |

If the product spans two rows, blend toward the one matching the *primary user goal*. Hybrid products
(commerce+social, SaaS+content) inherit the register of whichever surface the user is on.

## 3. Design dials (1–10) — record chosen values in the brief
Faithful to ui-ux-pro-max's `--variance / --motion / --density` sliders (ranges verbatim from its CLI,
including the density px sub-ranges — treated here as **guidance to map onto the project's spacing scale**,
never emitted as literal px).

- **variance** — visual risk, asymmetry, decoration.
  - **1–3 Centered/minimal** — symmetric, balanced grids, restrained decoration (Minimalism-biased).
  - **4–7 Balanced** — contemporary, moderate asymmetry, standard compositional patterns.
  - **8–10 Bold/asymmetric** — dynamic arrangement, experimental (Brutalism / Bento-biased).
- **motion** — animation ambition & choreography.
  - **1–3 Subtle** — opacity fades, single-element, ~150–200ms.
  - **4–7 Standard** — scroll/stagger reveals, list entrances, page transitions with spatial continuity, ~150–300ms.
  - **8–10 Complex** — pin/scrub, shared-element (Flip), split-text, multi-layer parallax, orchestrated sequences.
- **density** — information per screen; drives the spacing scale.
  - **1–3 Spacious** — generous padding/gaps; guidance range ~24–96px → map to the project's upper spacing steps. For marketing, hero, reading.
  - **4–7 Standard** — balanced; guidance range ~16–64px → mid spacing steps. Default.
  - **8–10 Dense** — compact; guidance range ~8–32px → lower spacing steps. For dashboards, analytics, data-heavy tools.

**Tune per screen, not just per product.** A reading/marketing view leans spacious (density ~2–3); a data
table or analytics view leans dense (~7–9). Motion is usually product-wide (a serious tool stays low even
on its landing page). State the three dial values and a one-line reason in the brief; when motion > 0, also
name the motion tier (§6).

## 4. Conditional reasoning engine — IF condition → THEN adjustment
This is the branching logic that makes the register adaptive rather than a lookup table. Each rule fires
from a detected condition, adjusts dials/tokens/patterns, names the **anti-pattern it prevents**, and
carries a **severity**. Severity semantics match the source: **HIGH** = hard constraint / blocks the
choice; **MEDIUM** = strong recommendation, override only with a stated reason. Apply the priority-1..3
rules (accessibility, touch, performance) as **non-negotiable** regardless of register.

**Priority hard constraints (apply first, always — severity HIGH):**
- **P1 accessibility** → enforce contrast (AA min, AAA for trust/public domains), visible focus rings,
  no color-as-only-signal, meaningful alt text/labels. *Prevents:* low-contrast, color-only status.
- **P2 touch & interaction** → interactive targets ≥ the platform's comfortable minimum, adequate spacing
  between tappable elements, explicit loading/feedback. *Prevents:* cramped tap targets, silent waits.
- **P3 performance** → responsive/next-gen imagery, lazy-load below fold, guard layout-shift. *Prevents:*
  slow rendering, janky first paint.

**Register-shaping rules:**

| # | IF condition | THEN adjustment | Anti-pattern prevented | Severity |
|---|--------------|-----------------|------------------------|----------|
| 1 | `if_trust_critical` (legal / finance / gov / health / insurance) | variance ≤ 4, motion ≤ 4; high-contrast neutral base + single trust accent; make credentials / sourcing / citations prominent | high-variance/high-motion on a trust domain (reads as untrustworthy); hidden credentials | HIGH |
| 2 | `if_data_heavy` (analytics / dashboard / admin / monitoring) | density 7–10; maximize data-ink, mute chrome; semantic status roles (success/warning/alert); virtualize long lists; provide filter + export | ornate decoration on data UI; no filtering; unreadable chart color; color-only meaning | HIGH |
| 3 | `if_ux_focused` / pure tool | prioritize minimalism; lower variance; keyboard shortcuts; minimal chrome; fast, small feedback motion | heavy chrome; complex onboarding; slow, decorative interactions | HIGH |
| 4 | `if_conversion_focused` (commerce / landing / lead-gen) | add urgency-accent role + prominent primary CTA; social proof, trust badges; strong visual hierarchy toward the action | buried CTA; text-heavy pages; missing trust signals | HIGH |
| 5 | `if_luxury` / premium | density 2–3 (more negative space); high contrast; refined type (serif-display role); restrained, *slow* motion; high-quality imagery | cheap visuals; fast/harsh animation; cramped premium page | HIGH |
| 6 | `if_brand_led` / creative / agency / campaign | variance 7–10, motion 6–9; allow one orchestrated hero moment; artistic freedom | generic corporate-minimal template on a differentiation-critical site | MEDIUM |
| 7 | `if_accessibility_mandatory` (gov / health / kids / education / public) | force AA/AAA contrast, focus rings, comfortable targets, no color-only meaning; cap motion; honor reduced-motion | motion-heavy, neon, low-contrast on a compliance domain | HIGH |
| 8 | `if_kids` / family | playful register; rounded forms; bouncy motion; big friendly type; strictly no ads, no dark patterns | age-inappropriate density; manipulative flows | HIGH |
| 9 | `if_content_first` (video / music / streaming) | dark-first surface base; poster/thumbnail-forward; chrome recedes; robust player affordances | cluttered layout; poor media-player UX | HIGH |
| 10 | `if_reading` / long_form (news / docs / notes) | density spacious–standard; comfortable measure (~60–75 char); strong type hierarchy; minimal motion; never parallax body copy | parallax/animation on body text; cramped reading column | MEDIUM |
| 11 | `if_real_time` (dashboards / IoT / logistics / security) | live-update affordance; status-semantic roles; high contrast; timestamped freshness | static “tracking” with no live state; slow updates | HIGH |
| 12 | `if_dashboard` within an otherwise-light domain (e.g. finance/crypto/security) | switch that surface to dark-mode base + higher density; keep marketing surfaces light | forcing one mode across incompatible surfaces; eye strain in-context | MEDIUM |
| 13 | `if_pre_launch` / MVP | waitlist or interactive-demo pattern; keep it simple; show the product fast | over-built static site with no product proof | MEDIUM |
| 14 | `if_collaboration` | presence indicators, real-time cursors, activity/status | no presence; cluttered multi-user UI | MEDIUM |
| 15 | `if_video_ready` / demo available | lead with hero video or interactive demo (with autoplay/mute controls) | static hero when motion proof exists | MEDIUM |
| 16 | `if_keyword_conflict_with_system` (request keyword fights the established look) | **Step-0 clarify** before shifting register; confirm the user wants a deliberate change | accidental register drift; fighting the design system | HIGH |

Rules stack: run every matching rule, resolve conflicts by severity (HIGH beats MEDIUM), and when two HIGH
rules disagree, prefer the one protecting trust/accessibility, then state the trade-off in the brief.

## 5. Style-family catalog — per-family specs (roles, not values)
Pick the family that fits the register **only if the project has no established look**; otherwise the
existing system's family governs and you match it. Never mix incompatible families on one surface (e.g.
flat + skeuomorphic, brutalist + glass) — that is an anti-pattern. Traits are described as **roles** so
they translate to any token system. (Source: ui-ux-pro-max's 71-style database.)

| Family | Best for (register) | Avoid for | Light/Dark | Complexity | A11y caution | Defining traits (roles) |
|--------|--------------------|-----------|-----------|-----------|-------------|-------------------------|
| Minimalism / Swiss | enterprise, SaaS, dashboards, docs | playful/creative brands | both | Low | strong (AAA-capable) | monochrome + one accent; generous whitespace; subtle ~200ms hover; sharp restrained shadow |
| Swiss Modernism 2.0 | corporate, editorial, museums, pro services, docs | children, entertainment, emotional storytelling | both | Low | strong (AAA) | strict grid + mathematical ratios; single vibrant accent; no gradients; typographic hierarchy |
| Flat Design | web/mobile apps, MVPs, SaaS | premium/luxury, 3D, artistic | both | Low | strong (AAA) | solid bright fills (4–6 max); no gradients/shadows; simple color/opacity hover ~150–200ms |
| Material-style | broad app UIs, cross-platform product | ultra-minimal luxury, print-first | both | Low–Med | strong | elevation shadow scale; ink-ripple feedback; bold color roles; grid + baseline rhythm |
| Neumorphism | health/wellness, meditation | complex apps, a11y-critical | light-first (dark partial) | Med | weak — low contrast, verify 4.5:1 | soft dual (inner+outer) shadow; low-contrast surface; gentle ~150ms press |
| Soft UI Evolution | modern enterprise, SaaS, wellness, pro tools | extreme minimalism, legacy | both | Med | good (AA+) | softened shadows (clearer than neumorphism); accessible pastel roles; ~200–300ms transitions |
| Glassmorphism | modern SaaS, fintech dashboards, IoT | low-contrast bg, a11y-critical | both | Med | verify 4.5:1 over blur | backdrop blur; translucent surface roles; vibrant accent; light reflection edge |
| Liquid Glass | premium SaaS, high-end commerce, luxury portfolio | perf-limited, a11y-critical, dense data | both | High | verify text contrast | morphing/fluid ~400–600ms; iridescent shift; dynamic blur; chromatic edges |
| Claymorphism | education, kids, creative tools | formal corporate, medical, legal | light-first (dark partial) | Med | verify 4.5:1 | puffy inner+outer shadow; pastel roles; soft ~200ms press; rounded chunky forms |
| Brutalism | design portfolios, artistic, statement sites | corporate, conservative industries | both | Low | AAA-capable if contrast held | raw/instant transitions; sharp corners; oversized bold type; primary color slabs |
| Neubrutalism | Gen-Z brands, startups, creative | luxury, finance, health, conservative | both | Low | AAA-capable | hard offset shadow (solid, no blur); instant transitions; bold type; high-contrast primaries |
| Bento-grid | dashboards, product pages, portfolios, Apple-style marketing | dense data tables, text-heavy, real-time | both | Low | AA | varied-span grid cells; generous rounding; subtle ~1.02 hover scale; card containers |
| Skeuomorphism | legacy, gaming, luxury simulation | modern enterprise, a11y-critical | partial/partial | High | weak — textures reduce readability | realistic material textures; deep layered shadows; perspective depth |
| 3D & Hyperrealism | gaming, product showcase, immersive | low-end mobile, a11y-critical | partial/partial | High | not accessible by default | WebGL/3D scenes; physical lighting; multi-layer parallax; rich gradient roles |
| Editorial / Magazine | news, blogs, long-form, publishing | dashboards, apps, catalogs, real-time | both | Low | strong (AAA) | high-contrast B/W + accent; multi-column type; pull-quotes; scroll reveal; page-flip feel |
| Dark Mode (OLED) | night apps, coding platforms, media, eye-strain contexts | print-first, high-brightness outdoor | dark-only | Low | strong (AAA) | near-black surface base; minimal text-glow; neon/gold accent roles; low light emission |
| Modern Dark (cinema/mobile) | premium mobile media, entertainment | daytime-utility, print | dark-first | Med | good | deep surface; cinematic contrast; restrained accent; poster-forward |
| Cyberpunk / HUD-FUI | gaming, crypto, sci-fi, security ops, dev tools | corporate, health, family, conservative | dark-only | Med | limited (dark+neon) — verify | neon glow; scanline/glitch accents; terminal-green roles; angular framing |
| Retro-Futurism / Vaporwave | gaming, entertainment, music, nostalgia | conservative, corporate | dark-focused | Med | high-strain — verify | CRT scanlines; neon+duotone; glow + glitch; 80s palette roles |
| Y2K | fashion, music, Gen-Z, nostalgia marketing | B2B, health, finance, conservative | light (dark partial) | Med | verify contrast | metallic/chrome gradients; glossy buttons; iridescent overlays; bubble forms |
| Memphis | creative agencies, music, youth brands, events | corporate finance, health, legal, conservative | both | Med | verify contrast | bold geometric shapes; clashing patterns; rotated/clipped forms; blend-mode accents |
| Bauhaus | branding-forward mobile, onboarding, artisan/design | enterprise dashboards, a11y-critical, dense data | light (dark partial) | Med | AA — verify yellow-on-light | primary red/blue/yellow roles; hard offset shadow; dot-grid; mechanical press |
| Organic / Biophilic | wellness, sustainability, eco, meditation, organic food | tech-forward, gaming, industrial | both | Low | AA | organic curves + varied rounding; earth/nature color roles; natural soft shadow; flowing shapes |
| Biomimetic / Organic 2.0 | biotech, advanced health, generative art | standard SaaS, data grids, strict corporate | both | High | good | breathing/growth animation; fluid morph; physics-based movement; bioluminescent accent roles |
| Gradient Mesh / Aurora | hero sections, creative, music, fashion, premium | data UIs, text-heavy, a11y-critical | both | Med | verify text over gradient | large flowing multi-stop gradient; slow 8–12s color morph; iridescent overlays |
| E-Ink / Paper | reading apps, journals, distraction-free writing, slow-living | gaming, video, high-energy marketing, dark-dependent | light-only (invert only) | Low | strong (AAA) | paper-white surface; ink-black text; grain/noise; sharp page-turn (no fade) |
| Minimalist Monochrome | luxury fashion mobile, editorial, avant-garde portfolio | colorful/friendly consumer apps, warmth-needed | light-enforced (section-invert) | Med | strong (AAA pure B/W) | pure black/white; no shadows (strict 2D); full-bleed rules; instant invert on active |
| AI-Native / Zero-Interface | AI chat, assistants, voice, smart home | complex workflows, data-entry-heavy, legacy | both | Low | good–excellent | conversational surface; streaming-text affordance; progressive disclosure; neutral base + restrained accent |
| Motion-Driven | storytelling, interactive portfolios | data dashboards, a11y-critical, low-power | both | High | honor reduced-motion | scroll-triggered reveals; parallax layers; 300–400ms orchestration; state-emphasis motion |

Additional cataloged families available for edge cases (same role-based discipline applies): Micro-interactions,
Vibrant & Block-based, Aurora UI, Dimensional Layering, Exaggerated Minimalism, Kinetic Typography, Spatial UI,
Pixel Art, Chromatic Aberration, Vintage Analog. Reach for these only when a mainstream family cannot carry the
register.

## 6. Motion tiers (bind to the motion dial)
ui-ux-pro-max ships motion as **3 intensity tiers × preset categories** (17 presets). Name the tier in the
brief; the implementer maps it to the project's animation tokens/utilities. Always pair with a
reduced-motion fallback.

- **Subtle (motion 1–3)** — hover micro-feedback (<2px displacement, ~150–200ms), gentle scroll fade
  (8–16px), light skeleton shimmer. Transform/opacity only (compositor-friendly).
- **Standard (motion 4–7)** — staggered list/section reveals (cap ~8 items), standard page transitions
  (exit faster than entrance), moderate parallax on decorative layers only.
- **Complex (motion 8–10)** — pinned scrub / scrollytelling, shared-element (Flip) transitions, split-text
  headline reveals, multi-layer parallax. Reserve for ≤1–2 focal moments per screen; test on mid-tier
  mobile. Never animate body copy or layout-affecting properties.

## 7. How the strategist uses this
1. **Classify the product** (§1): parent family → domain → audience → keywords → existing-system check.
2. **Pick the register row** (§2): read register, formality, and the starting var/mot/den ranges.
3. **Set the dials** (§3): choose concrete 1–10 values (per screen where it differs), note the px→scale
   mapping for density.
4. **Run the conditional engine** (§4): fire every matching IF rule, apply P1–P3 hard constraints, resolve
   conflicts by severity, and record which anti-patterns you are actively preventing.
5. **Pick a compatible style family** (§5) — only if no established look exists; otherwise match the system.
   Confirm it is not on the family's "avoid for" list and its a11y caution is satisfiable.
6. **Name the motion tier** (§6) if motion > 0.
7. **Hand token ROLES to the brief**: register + formality + dial values + fired rules + family + motion
   tier + rationale go at the top of `brief.md`. Every color/space/radius named downstream is a **token
   role**, never a raw value or a foreign framework's class name. If the request's keywords conflict with
   the existing system, that is a **Step-0 clarify** before anything ships.

## 8. Anti-patterns for register selection
- Defaulting every product to the same "modern SaaS" look regardless of domain (rule 1/6 violation).
- Ignoring an existing design system and imposing personal taste (rule 16 violation).
- High-variance / high-motion on a trust-critical domain (legal/finance/health/gov) — reads as untrustworthy.
- Dense dials on a marketing/first-impression screen; spacious dials on a power-user dashboard.
- Animating or parallaxing body copy in a reading/long-form register.
- Emitting raw values or a foreign framework's class names instead of the project's token roles.
- Choosing a style family the team can't maintain in their stack (e.g. heavy glass/3D where performance
  or accessibility is a hard requirement), or picking a family listed under its own "avoid for".
- Skipping the P1–P3 hard constraints because the register is "just marketing" — they are non-negotiable.
