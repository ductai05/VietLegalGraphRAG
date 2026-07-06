# Design System — Agent Instructions

This skill describes the visual design language for all UI output. Every component, layout, and page should follow the design specs in the module files below. These describe _what the design looks like_ — you choose how to implement the styles.

## Style

A radically minimal, blank-canvas interface — pure #FFFFFF page surface from edge to edge, near-zero chromatic saturation, and Open Sans doing all the visual heavy-lifting. Black (#000000) is the only filled color, #E5E7EB is the only divider, and #F5F5F5 is the only surface tone for cards layered over the page. **Cards use 24px border radius only.** Buttons, alerts, badges, and inputs use **9999px pill** geometry. No shadows, no gradients on chrome, no decorative illustration — color enters the page only through editorial photography. Display typography is tightly tracked at -0.03em so headlines feel carved rather than set; body sizes carry zero tracking.

## Before Writing Any Code

1. **Read every module that applies.** For a landing page, read at minimum: `layout.md`, `typography.md`, `colors.md`, `buttons.md`, `cards.md`, `shadows.md`, `radius.md`, `borders.md`. Do NOT write JSX until you have loaded all relevant modules.

## Critical Rules

- **Tokens are AGNOSTIC, framework-independent:** The tokens defined in the `.md` files (like `neutral-primary-soft`, `heading`, `border-default`) are agnostic design system tokens. They are NOT literal class names from any styling framework or library. Do not assume a token name maps directly to a utility class — you must implement the mapping yourself in CSS custom properties or whatever styling layer your project uses.

- **Cross-reference modules.** A card containing buttons must satisfy both `cards.md` AND `buttons.md`.
- **Dark mode is automatic.** The CSS custom properties resolve differently in light/dark via `@media (prefers-color-scheme: dark)`. Never manually swap colors.
- **Every interactive element needs hover, focus, and disabled states** — defined in the relevant module.
- **Use semantic HTML:** proper heading hierarchy (`h1`→`h6`), `<button>` for actions, `<a>` for navigation, ARIA attributes where needed.
- **Border radius split:** Cards = 24px only. Buttons, alerts, badges, and inputs = 9999px pill only. See `radius.md`.

## Module Index

### Foundation (read first for any UI work)

- [colors.md](colors.md) — all background, text, and border color tokens
- [typography.md](typography.md) — heading scale, paragraphs, labels, links
- [layout.md](layout.md) — spacing rhythm, containers, animation, visual depth
- [radius.md](radius.md) — border-radius scale
- [shadows.md](shadows.md) — elevation tokens
- [borders.md](borders.md) — border widths and styles

### Components

- [buttons.md](buttons.md) — button variants, sizes, states
- [button-group.md](button-group.md) — grouped button structure
- [cards.md](cards.md) — card structure, background, interactivity
- [inputs.md](inputs.md) — form controls, labels, states
- [alerts.md](alerts.md) — alert variants
- [badges.md](badges.md) — badge variants, sizes, dismissible chips
- [lists.md](lists.md) — list components
- [avatars.md](avatars.md) — avatar variants, sizes, indicators
- [icon-shapes.md](icon-shapes.md) — icon containers

### Complex Components

- [accordion.md](accordion.md) — accordion variants
- [dropdown.md](dropdown.md) — dropdown menus
- [modals.md](modals.md) — modal dialogs
- [tabs.md](tabs.md) — tab navigation
- [tables.md](tables.md) — table structure
- [pagination.md](pagination.md) — pagination components
- [sidebars.md](sidebars.md) — sidebar navigation
- [radios-checkboxes-toggle.md](radios-checkboxes-toggle.md) — selection controls
- [tooltips-popovers.md](tooltips-popovers.md) — tooltips and popovers
- [content.md](content.md) — grid system, responsiveness

---

## Source file: `accordion.md`

# Accordion

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Wrapper:** full width, 1px border (border-default color, #E5E7EB), 9999px radius — clips first/last item corners into a pill silhouette
- **Item separator:** 1px bottom border (border-default, #E5E7EB) on every item except last

## Trigger (Button)

- **Layout:** flex, space-between, full width
- **Padding:** 24px horizontal, 16px vertical
- **Font:** 16px, 500 (medium) weight, Open Sans
- **Text color:** heading (#000000)
- **Background:** neutral-primary-soft (#FFFFFF)
- **Hover:** neutral-secondary-medium background (#F5F5F5)
- **Focus:** outline none, 2px ring in brand color (#000000)
- **Transition:** colors, 150ms
- **Open state:** neutral-secondary-medium background (#F5F5F5)

## Panel (Content)

- **Padding:** 24px horizontal, 16px vertical
- **Background:** neutral-primary-soft (#FFFFFF)
- **Top border:** 1px, border-default color (#E5E7EB)
- **Font:** 16px, body color (#666666), 1.6 line-height

## Chevron Icon

- Size: 16x16px
- Color: body text color (#666666)
- Closed: 0deg rotation
- Open: 180deg rotation
- Transition: transform, 150ms

## Variants

### Default (Collapse)

One panel open at a time. Items stacked inside a single shared bordered/rounded wrapper.

### Separated Cards

Each item is independent — has its own 1px border (#E5E7EB), 9999px radius, and NO shadow. 8px bottom margin between items. No shared outer border.

### Always Open

Multiple panels can expand simultaneously. Same styling as Default.

### Flush

No outer border. Trigger and panel have transparent backgrounds. Only bottom border dividers between items. Use inside containers that already provide a background.

## States

| State    | Trigger appearance                                                    |
| -------- | --------------------------------------------------------------------- |
| Closed   | heading text (#000000), neutral-primary-soft background (#FFFFFF)     |
| Open     | heading text (#000000), neutral-secondary-medium background (#F5F5F5) |
| Hover    | neutral-secondary-medium background (#F5F5F5)                         |
| Focus    | 2px brand ring (#000000), no outline                                  |
| Disabled | fg-disabled text (#8F8F8F), not-allowed cursor, no hover/focus        |

---

## Source file: `alerts.md`

# Alerts

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Padding:** 16px 20px
- **Radius:** 9999px (pill geometry — every alert uses 9999px pill radius only)
- **Border:** 1px, border-default (#E5E7EB)
- **Heading:** 16px, 500 (medium) weight, heading color (#000000)
- **Body:** 14px, 400 (regular) weight, 1.5 line-height, body color (#666666)
- **Shadow:** none

## Variants

All alert variants share the same neutral palette — intent is communicated through the icon and heading text, never through colored backgrounds or borders.

### Brand

- **Background:** brand-softer (#FAFAFA)
- **Border:** border-brand-subtle (#E5E7EB)
- **Text:** fg-brand-strong (#000000)

### Success

- **Background:** success-soft (#F5F5F5)
- **Border:** border-success-subtle (#E5E7EB)
- **Text:** fg-success-strong (#000000)

### Danger

- **Background:** danger-soft (#F5F5F5)
- **Border:** border-danger-subtle (#E5E7EB)
- **Text:** fg-danger-strong (#000000)

### Warning

- **Background:** warning-soft (#F5F5F5)
- **Border:** border-warning-subtle (#E5E7EB)
- **Text:** fg-warning (#000000)

---

## Source file: `avatars.md`

# Avatars

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Circular shape:** fully rounded (9999px)
- **Rounded square shape:** 6.08px radius (image-containing — this is the precise card-image radius)
- **Default size:** 40x40px
- **Image fit:** cover

## Sizes

| Size        | Dimensions | Radius |
| ----------- | ---------- | ------ |
| Extra Small | 18x18px    | 9999px |
| Small       | 24x24px    | 9999px |
| Base        | 32x32px    | 9999px |
| Large       | 44x44px    | 9999px |
| XL          | 56x56px    | 9999px |
| 2XL         | 64x64px    | 9999px |

The "rounded square" avatar uses 6.08px in every size — that value is intentional and must be exact.

## Bordered Avatar

- 4px padding, fully rounded (9999px), 1px outline in border-default color (#E5E7EB)
- No box-shadow ring — separation comes from the outline alone

## Stacked Avatars

- Displayed in a row (flex)
- Each avatar: 40x40px, fully rounded (9999px), 2px border in border-buffer color (#FFFFFF)
- Overlap: -16px negative margin on all except first

### Stacked Counter

- Same size as avatars (40x40px), fully rounded (9999px)
- Background: dark-strong (#000000), text: white, 12px font, 500 (medium) weight
- Same overlap margin as other avatars

## Avatar with Text

- Flex row, 12px gap between avatar and text
- Avatar: 40x40px, fully rounded (9999px), cover fit
- Name: heading color (#000000), 500 (medium) weight
- Subtitle: 14px, body color (#666666)

---

## Source file: `badges.md`

# Badges

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Border:** 1px, border-default (#E5E7EB)
- **Default radius:** 9999px (pill is the only badge geometry — no square or reduced-radius variants)
- **Pill radius:** 9999px (required for every badge)
- **Shadow:** none

## Sizes

| Size            | Font size | Horizontal padding | Vertical padding |
| --------------- | --------- | ------------------ | ---------------- |
| Default (small) | 12px      | 10px               | 3px              |
| Large           | 14px      | 12px               | 5px              |

Horizontal padding is increased relative to a square chip because pill geometry needs visual side room to register as a pill.

## Variants

All variants share the same neutral palette — intent is signaled by an inline icon or label, never by a colored background.

### Brand

- **Background:** brand-softer (#FAFAFA)
- **Border:** border-brand-subtle (#E5E7EB)
- **Text:** fg-brand-strong (#000000)

### Alternative (Neutral Soft)

- **Background:** neutral-primary-soft (#FFFFFF)
- **Border:** border-default (#E5E7EB)
- **Text:** heading (#000000)

### Gray (Neutral Medium)

- **Background:** neutral-secondary-medium (#F5F5F5)
- **Border:** border-default (#E5E7EB)
- **Text:** heading (#000000)

### Danger

- **Background:** danger-soft (#F5F5F5)
- **Border:** border-danger-subtle (#E5E7EB)
- **Text:** fg-danger-strong (#000000)

### Success

- **Background:** success-soft (#F5F5F5)
- **Border:** border-success-subtle (#E5E7EB)
- **Text:** fg-success-strong (#000000)

### Warning

- **Background:** warning-soft (#F5F5F5)
- **Border:** border-warning-subtle (#E5E7EB)
- **Text:** fg-warning (#000000)

### Dark

- **Background:** dark (#000000)
- **Border:** transparent
- **Text:** white

## Pill Badges

Use 9999px radius — this is the same as the default; the system has no non-pill badge variant. The "pill" naming is preserved for compatibility.

## Badges with Icons

- Icon size (default): 12x12px
- Icon size (large): 14x14px
- Icon spacing: 6px margin next to label

## Icon-only Badge

Square shape — equalize dimensions to 24x24px, no horizontal text padding. Radius stays 9999px (becomes a circle).

## Dismissible Badges

Badge content + a close button. Close button hover backgrounds per variant:

| Variant     | Close button hover background |
| ----------- | ----------------------------- |
| Brand       | brand-soft (#F5F5F5)          |
| Alternative | neutral-tertiary (#F5F5F5)    |
| Gray        | neutral-quaternary (#E5E7EB)  |
| Danger      | danger-medium (#E5E7EB)       |
| Success     | success-medium (#E5E7EB)      |
| Warning     | warning-medium (#E5E7EB)      |

## Dot / Notification Badge

- Positioned absolutely: -4px top, -4px right
- Size: 10x10px, fully rounded (9999px)
- 2px border in border-buffer color (#FFFFFF)
- Background: danger (#000000)

---

## Source file: `borders.md`

# Borders

## Width Scale

| Context                          | Width |
| -------------------------------- | ----- |
| Default (inputs, buttons, cards) | 1px   |
| Emphasis / focus                 | 1px   |

## Rules

- Use solid borders by default
- Dashed borders only for special cases like file dropzones
- Components in the same family must use matching border widths
- Never mix border widths within a single component
- Border color is exclusively #E5E7EB (border-default) — never darken, tint, or substitute another value for dividers and hairlines
- The single exception is filled #000000 buttons, which omit a visible border (use transparent or matching the background)

## Usage

| Context                      | Width                                                             |
| ---------------------------- | ----------------------------------------------------------------- |
| Inputs / selects / textareas | 1px default; 1px on focus or error (color shifts to #000000)      |
| Buttons                      | 1px for outlined variants; transparent for filled #000000 buttons |
| Cards / containers           | 1px in #E5E7EB only; never stack heavy borders                    |

---

## Source file: `button-group.md`

# Button Groups

> Dependencies: `buttons.md`, `colors.md`, `radius.md`

## Core Specs

- **Wrapper:** inline-flex, 9999px radius (pill silhouette across the entire group), no shadow
- **Children overlap:** -1px left margin on all except first button
- **Buttons inside the group must NOT have individual shadows.** The wrapper has no shadow either — the group is intentionally flat.

## Anatomy

### Wrapper

- Display: inline-flex
- Radius: 9999px
- Shadow: none

### First Button

- 9999px radius on inline-start side only, 0 on inline-end (the start cap of the pill)

### Middle Button(s)

- No radius (0 on all corners)

### Last Button

- 9999px radius on inline-end side only, 0 on inline-start (the end cap of the pill)

### All buttons except first

- -1px left margin to overlap borders

## Rules

- Buttons inside groups follow all styles from `buttons.md` (background, border, focus rings) — including the no-shadow / no-glint rules
- Icon-only buttons: 16x16px icon, match height of text buttons
- The group's outer silhouette must read as a single pill — never mix the 9999px end caps with a 6.08px image-card radius inside the same group

---

## Source file: `buttons.md`

# Buttons

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Core Specs (every button except ghost and disabled)

- **Radius:** 9999px (pill geometry on every button — no square or reduced-radius variants)
- **Border:** 1px solid (transparent on filled #000000 brand buttons; #E5E7EB on outlined variants)
- **Shadow:** none — buttons never carry a box-shadow
- **Glint effect:** disabled. The glint variables (`--color-1-400`, `--color-1-700`) resolve to fully transparent values; do NOT layer inset highlights or outer color glows on any button
- **Font weight:** 500 (medium)
- **Font:** Open Sans
- **Box sizing:** border-box
- **Transition:** color and background-color transitions on hover

## Sizes

| Size           | Font size | Horizontal padding | Vertical padding |
| -------------- | --------- | ------------------ | ---------------- |
| Extra small    | 12px      | 14px               | 6px              |
| Small          | 14px      | 16px               | 8px              |
| Base (default) | 14px      | 20px               | 10px             |
| Large          | 16px      | 24px               | 12px             |
| Extra large    | 16px      | 28px               | 14px             |

Horizontal padding is slightly more generous than typical because pill buttons need extra side room to read as pills, not capsules.

## Variants

### Brand

- **Background:** brand token (#000000)
- **Border:** transparent
- **Text:** white
- **Hover:** brand-strong background (stays #000000); apply a subtle opacity shift (e.g. 90%) for hover feedback since the color cannot deepen
- **Focus ring:** 2px, brand-medium color (#E5E7EB) offset, with a 1px #000000 outline
- **Glint:** none

### Secondary

- **Background:** neutral-secondary-medium (#F5F5F5)
- **Border:** border-default (#E5E7EB)
- **Text:** heading color (#000000)
- **Hover:** neutral-tertiary-medium background (#F5F5F5), heading text color
- **Focus ring:** 2px, neutral-tertiary color
- **Glint:** none

### Tertiary

- **Background:** neutral-primary-soft (#FFFFFF)
- **Border:** border-default (#E5E7EB)
- **Text:** heading color (#000000)
- **Hover:** neutral-secondary-medium background (#F5F5F5), heading text color
- **Focus ring:** 2px, neutral-tertiary-soft color
- **Glint:** none

### Success

- **Background:** success token (#000000)
- **Border:** transparent
- **Text:** white
- **Hover:** success-strong background (#000000) with subtle opacity shift
- **Focus ring:** 2px, success-medium color
- **Glint:** none

### Danger

- **Background:** danger token (#000000)
- **Border:** transparent
- **Text:** white
- **Hover:** danger-strong background (#000000) with subtle opacity shift
- **Focus ring:** 2px, danger-medium color
- **Glint:** none

### Warning

- **Background:** warning token (#000000)
- **Border:** transparent
- **Text:** white
- **Hover:** warning-strong background (#000000) with subtle opacity shift
- **Focus ring:** 2px, warning-medium color
- **Glint:** none

### Dark

- **Background:** dark token (#000000)
- **Border:** transparent
- **Text:** white
- **Hover:** dark-strong background (#000000) with subtle opacity shift
- **Focus ring:** 2px, neutral-tertiary color
- **Glint:** none

### Ghost (NO shadow, NO glint)

- **Radius:** 9999px (pill — same as every other button)
- **Background:** transparent
- **Border:** transparent
- **Text:** heading color (#000000)
- **Hover:** neutral-secondary-medium background (#F5F5F5)
- **Focus ring:** 2px, neutral-tertiary color
- **No shadow, no glint effect**

### Disabled (NO shadow, NO glint)

- **Background:** disabled token (#F5F5F5)
- **Border:** border-default-medium (#E5E7EB)
- **Text:** fg-disabled color (#8F8F8F)
- **Cursor:** not-allowed
- **No hover, no focus, no shadow, no glint**

## Icons in Buttons

- Icon size: 16x16px
- Spacing: 8px gap between icon and label
- Layout: inline-flex, vertically centered
- Icon color inherits from button text color — never tint with an accent
- #000000 is the ONLY filled-button background color in the system — there are no colored CTAs (no blue, green, orange primary buttons). All status variants (success/danger/warning) keep the same #000000 fill; intent is communicated through the surrounding context, not the button color

---

## Source file: `cards.md`

# Cards

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `typography.md`

## Core Specs

- **Background:** neutral-secondary-medium (#F5F5F5) — every card laid over a section surface uses #F5F5F5 to separate from the #FFFFFF page
- **Border:** none by default; if a hairline is needed, 1px in border-default (#E5E7EB)
- **Radius:** 24px — **every card uses 24px border radius only**, including image-containing cards and thumbnail clips
- **Shadow:** none — cards have NO shadow under any circumstance. Separation comes from the #F5F5F5 surface tone against the #FFFFFF page, not from depth

## Card Heading

- Desktop: 20px, 500 (medium) weight, heading color (#000000)
- Mobile: 18px, 500 (medium) weight, heading color (#000000)
- Never skip heading levels — the page hierarchy must logically arrive at the card heading level.

## States

### Static Card (no interactivity)

- Background: neutral-secondary-medium (#F5F5F5)
- Border: none (or 1px border-default if a hairline is required)
- Radius: 24px
- Shadow: none
- No hover styles. Non-interactive cards must NOT have hover background changes.

### Interactive Card (clickable)

- Same base styles as static card
- Hover: subtle opacity shift on the #F5F5F5 surface (e.g. mix toward #ECECEC) — never introduce a colored hover state and never add a shadow on hover
- Transition: background-color
- Cursor: pointer

## Rules

- Background: neutral-secondary-medium (#F5F5F5) for cards layered over section surfaces
- Radius: **24px only** on every card variant — use 24px on the card shell and on any embedded image clip inside the card
- Never use pill (9999px) or 6.08px radius on cards
- Shadow: none on every card variant — flat by design
- Interactive hover: tonal shift on the surface only, no shadow, no border darkening
- Non-interactive: no hover styles
- Color may only enter the card through embedded photography or editorial imagery; never tint the card chrome itself

---

## Source file: `colors.md`

# Color Tokens

## Background Tokens

### Neutral

| Token                    | Light   | Dark    |
| ------------------------ | ------- | ------- |
| neutral-primary-soft     | #FFFFFF | #000000 |
| neutral-primary          | #FFFFFF | #000000 |
| neutral-primary-medium   | #FFFFFF | #0A0A0A |
| neutral-primary-strong   | #FFFFFF | #141414 |
| neutral-secondary-soft   | #FFFFFF | #000000 |
| neutral-secondary        | #FFFFFF | #0A0A0A |
| neutral-secondary-medium | #F5F5F5 | #141414 |
| neutral-secondary-strong | #F5F5F5 | #1F1F1F |
| neutral-tertiary-soft    | #F5F5F5 | #0A0A0A |
| neutral-tertiary         | #F5F5F5 | #141414 |
| neutral-tertiary-medium  | #F5F5F5 | #1F1F1F |
| neutral-quaternary       | #E5E7EB | #1F1F1F |
| quaternary-medium        | #E5E7EB | #2A2A2A |
| gray                     | #E5E7EB | #2A2A2A |

### Brand

| Token        | Light   | Dark    |
| ------------ | ------- | ------- |
| brand-softer | #FAFAFA | #1A1A1A |
| brand-soft   | #F5F5F5 | #2A2A2A |
| brand        | #000000 | #FFFFFF |
| brand-medium | #E5E7EB | #404040 |
| brand-strong | #000000 | #FFFFFF |

### Status

| Token          | Light   | Dark    |
| -------------- | ------- | ------- |
| success-soft   | #F5F5F5 | #0A0A0A |
| success        | #000000 | #FFFFFF |
| success-medium | #E5E7EB | #1F1F1F |
| success-strong | #000000 | #FFFFFF |
| danger-soft    | #F5F5F5 | #0A0A0A |
| danger         | #000000 | #FFFFFF |
| danger-medium  | #E5E7EB | #1F1F1F |
| danger-strong  | #000000 | #FFFFFF |
| warning-soft   | #F5F5F5 | #0A0A0A |
| warning        | #000000 | #FFFFFF |
| warning-medium | #E5E7EB | #1F1F1F |
| warning-strong | #000000 | #FFFFFF |

### Button Glint (CSS custom properties, used for the glint box-shadow effect)

| Variable        | Light               | Dark                |
| --------------- | ------------------- | ------------------- |
| `--color-1-400` | rgba(255,255,255,0) | rgba(255,255,255,0) |
| `--color-1-700` | rgba(0,0,0,0)       | rgba(0,0,0,0)       |

### Utility

| Token       | Light   | Dark    |
| ----------- | ------- | ------- |
| dark        | #000000 | #000000 |
| dark-strong | #000000 | #0A0A0A |
| disabled    | #F5F5F5 | #1F1F1F |

### Accent

| Token   | Value (same both modes) |
| ------- | ----------------------- |
| purple  | #000000                 |
| sky     | #000000                 |
| teal    | #000000                 |
| pink    | #000000                 |
| cyan    | #000000                 |
| fuchsia | #000000                 |
| indigo  | #000000                 |
| orange  | #000000                 |

## Text Color Tokens

### Base

| Token       | Light   | Dark    |
| ----------- | ------- | ------- |
| white       | #FFFFFF | #FFFFFF |
| black       | #000000 | #000000 |
| heading     | #000000 | #FFFFFF |
| body        | #666666 | #B3B3B3 |
| body-subtle | #8F8F8F | #8F8F8F |

### Brand

| Token           | Light   | Dark    |
| --------------- | ------- | ------- |
| fg-brand-subtle | #666666 | #B3B3B3 |
| fg-brand        | #000000 | #FFFFFF |
| fg-brand-strong | #000000 | #FFFFFF |

### Status

| Token             | Light   | Dark    |
| ----------------- | ------- | ------- |
| fg-success        | #000000 | #FFFFFF |
| fg-success-strong | #000000 | #FFFFFF |
| fg-danger         | #000000 | #FFFFFF |
| fg-danger-strong  | #000000 | #FFFFFF |
| fg-warning-subtle | #666666 | #B3B3B3 |
| fg-warning        | #000000 | #FFFFFF |
| fg-disabled       | #8F8F8F | #8F8F8F |

### Informational / Accent

| Token            | Light   | Dark    |
| ---------------- | ------- | ------- |
| fg-yellow        | #000000 | #FFFFFF |
| fg-info          | #000000 | #FFFFFF |
| fg-purple        | #000000 | #FFFFFF |
| fg-purple-strong | #000000 | #FFFFFF |
| fg-cyan          | #000000 | #FFFFFF |
| fg-indigo        | #000000 | #FFFFFF |
| fg-pink          | #000000 | #FFFFFF |
| fg-lime          | #000000 | #FFFFFF |

## Border Color Tokens

| Token                 | Light   | Dark    |
| --------------------- | ------- | ------- |
| border-dark           | #000000 | #FFFFFF |
| border-buffer         | #FFFFFF | #000000 |
| border-buffer-medium  | #FFFFFF | #0A0A0A |
| border-buffer-strong  | #FFFFFF | #141414 |
| border-muted          | #E5E7EB | #1F1F1F |
| border-light-subtle   | #E5E7EB | #1F1F1F |
| border-light          | #E5E7EB | #1F1F1F |
| border-light-medium   | #E5E7EB | #1F1F1F |
| border-default-subtle | #E5E7EB | #1F1F1F |
| border-default        | #E5E7EB | #1F1F1F |
| border-default-medium | #E5E7EB | #1F1F1F |
| border-default-strong | #E5E7EB | #1F1F1F |
| border-success-subtle | #E5E7EB | #1F1F1F |
| border-success        | #000000 | #FFFFFF |
| border-danger-subtle  | #E5E7EB | #1F1F1F |
| border-danger         | #000000 | #FFFFFF |
| border-warning-subtle | #E5E7EB | #1F1F1F |
| border-warning        | #000000 | #FFFFFF |
| border-brand-subtle   | #E5E7EB | #1F1F1F |
| border-brand-light    | #000000 | #FFFFFF |
| border-brand          | #000000 | #FFFFFF |
| border-dark-subtle    | #000000 | #1F1F1F |
| border-purple         | #000000 | #FFFFFF |
| border-orange         | #000000 | #FFFFFF |

## Semantic Usage Rules

- Page/section backgrounds: neutral-primary-soft (always #FFFFFF) — the entire page stays white wall-to-wall, never alternate section background colors
- Surface cards (cards layered on top of sections): neutral-secondary-medium (#F5F5F5)
- Footer background: brand (#000000), with white text inside it
- Primary buttons: brand background (#000000) — black is the only filled CTA color
- Headings: heading text color (#000000)
- Body text: body text color (#666666)
- Tertiary / disabled text: body-subtle (#8F8F8F)
- CTA links: fg-brand text color (#000000), underlined
- Default borders/dividers: border-default (#E5E7EB) — never darken or tint
- Status borders match intent: success → border-success, danger → border-danger, warning → border-warning
- Disabled: disabled background + fg-disabled text
- Color may only be introduced through photography or editorial imagery — never through UI backgrounds, button fills, or accent chrome

## Prohibited

- No raw hex/rgb values in component code — always use design tokens
- No colored accent (blue, green, orange, purple) on interactive elements or backgrounds — black is the only active color
- No brand text color for long-form paragraphs
- No accent text tokens (fg-purple, etc.) for body copy or navigation
- No background colors on section blocks — page stays #FFFFFF wall-to-wall
- No more than two typographic colors at once: heading (#000000) for primary and body (#666666) for secondary; body-subtle (#8F8F8F) is reserved for disabled/tertiary only
- No manual light/dark value swapping — let the CSS custom properties handle it

---

## Source file: `content.md`

# Content & Grid System

> Dependencies: `layout.md`, `typography.md`

## Containers

| Type               | Max width | Horizontal padding         |
| ------------------ | --------- | -------------------------- |
| Standard           | 1280px    | 24px                       |
| Internal (reading) | 720px     | — (45–75 char line length) |

## Vertical Padding

| Breakpoint        | Vertical padding |
| ----------------- | ---------------- |
| Mobile            | 64px             |
| Tablet (≥768px)   | 80px             |
| Desktop (≥1024px) | 96px             |

The minimum vertical gap between any two page sections is 64px on every breakpoint.

## Grid System

Mobile-first with flexible desktop configurations.

| Context                  | Gap  |
| ------------------------ | ---- |
| Standard content/cards   | 24px |
| Compact widgets/metadata | 16px |

### Responsive Columns

| Breakpoint            | Columns |
| --------------------- | ------- |
| Mobile (default)      | 1–2     |
| Small/Tablet (≥640px) | 2–4     |
| Desktop (≥1024px)     | 3–12    |

Full support for 6, 7, 8, 9+ column grids where needed.

## Breakpoints

| Name           | Width  |
| -------------- | ------ |
| Small          | 640px  |
| Medium         | 768px  |
| Large          | 1024px |
| Extra large    | 1280px |
| 2x Extra large | 1536px |

## Rules

- Always design mobile-first
- Use layout shifts (column → row) to accommodate horizontal space
- Lists: 24px indentation, 8px vertical gap between items
- Body copy: 16px, 1.6 line-height, 0 letter-spacing (no tracking at body sizes)
- All interactive links follow brand underline/hover protocol
- Page background is always #FFFFFF; section blocks never carry a colored fill

---

## Source file: `dropdown.md`

# Dropdown

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `inputs.md`

## Core Specs

### Chevron Icon

- Size: 16x16px
- Spacing: 6px left margin, -2px right margin
- Color: inherits from trigger button

### Menu Container

- Background: neutral-primary-soft (#FFFFFF)
- Border: 1px, border-default (#E5E7EB)
- Radius: 9999px is reserved for compact pill menus; for standard list menus use 6.08px so the menu reads as an image-card-style surface that frames the contained items
- Shadow: none — separation from the page comes from the 1px #E5E7EB hairline only
- Z-index: elevated above content

### Menu List

- Padding: 8px
- Font: 14px, body color (#666666), 500 (medium) weight, Open Sans

### Menu Item

- Layout: inline-flex, vertically centered, full width
- Padding: 12px horizontal, 8px vertical
- Radius: 9999px (pill items inside the menu)
- Hover: neutral-tertiary-medium background (#F5F5F5), heading text (#000000)
- Transition: colors, 150ms

## Trigger Sizes

| Size  | Font size | Horizontal padding | Vertical padding |
| ----- | --------- | ------------------ | ---------------- |
| Small | 14px      | 16px               | 8px              |
| Base  | 14px      | 20px               | 10px             |
| Large | 16px      | 24px               | 12px             |

Trigger uses 9999px pill radius (inherits from `buttons.md`).

## Icon-only Trigger

- Padding: 8px
- Min size: 44x44px
- Icon: 20x20px
- Radius: 9999px (circle)

## Variants

### Default

- Menu width: 200px, items have 9999px radius (pill rows)

### With Divider

- Top border (border-default, #E5E7EB) between child groups, skip first group

### With Header

- Header padding: 16px horizontal, 12px vertical
- Bottom border: border-default (#E5E7EB)
- Name: heading color (#000000), 14px, 600 (semibold) weight
- Email: body-subtle color (#8F8F8F), 14px, truncated

### With Icons

- Icon before label: 16x16px, 8px right margin, body color (#666666)
- On hover, icon color changes to heading (#000000)

### With Checkbox / Radio

- Inputs: 16x16px, 4px radius (the only sub-pixel exception, kept for visual reasons)
- Focus ring in brand-soft (#F5F5F5)
- Helper text: 12px, body-subtle color (#8F8F8F), 2px top margin

### With Search

- Search input at top of menu following `inputs.md` specs (9999px pill input)
- Left icon: 12px left padding, input 36px left padding

### Scrollable

- Max height: 240px, vertical scroll overflow

## States

| State            | Appearance                                                           |
| ---------------- | -------------------------------------------------------------------- |
| Focused trigger  | no outline, 2px brand ring (#000000)                                 |
| Hover item       | neutral-tertiary-medium background (#F5F5F5), heading text (#000000) |
| Active/open item | neutral-tertiary-soft background (#F5F5F5), heading text (#000000)   |
| Disabled item    | fg-disabled text (#8F8F8F), not-allowed cursor, no pointer events    |

---

## Source file: `icon-shapes.md`

# Icon Shapes

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- Box sizing: border-box
- Icon must be perfectly centered (inline-flex, centered both axes)
- Circle: fully rounded (9999px)
- Rounded square: 6.08px radius (matches the image-card radius for any container that holds visual content)

## Sizes

| Size | Container | Icon    |
| ---- | --------- | ------- |
| XS   | 24x24px   | 14x14px |
| SM   | 32x32px   | 16x16px |
| MD   | 40x40px   | 20x20px |
| LG   | 48x48px   | 24x24px |
| XL   | 56x56px   | 28x28px |

## Color Variants

All variants use the same neutral surface — color/intent is communicated by the icon glyph itself, not by colored chrome.

### Brand

- Shape: circle (9999px)
- Background: brand-softer (#FAFAFA)
- Icon color: fg-brand-strong (#000000)

### Gray

- Shape: circle (9999px)
- Background: neutral-secondary-soft (#FFFFFF)
- Icon color: body (#666666)

### Danger

- Shape: circle (9999px)
- Background: danger-soft (#F5F5F5)
- Icon color: fg-danger-strong (#000000)

### Success

- Shape: circle (9999px)
- Background: success-soft (#F5F5F5)
- Icon color: fg-success-strong (#000000)

### Warning

- Shape: circle (9999px)
- Background: warning-soft (#F5F5F5)
- Icon color: fg-warning (#000000)

---

## Source file: `inputs.md`

# Inputs

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Display:** block, full width
- **Radius:** 9999px (pill geometry — **every input** including single-line fields, conversational inputs, and multi-line textareas uses 9999px pill radius)
- **Border:** 1px, border-default-medium (#E5E7EB)
- **Background:** neutral-secondary-medium (#F5F5F5)
- **Shadow:** none
- **Font:** 16px, Open Sans, heading color (#000000)
- **Padding:** 20px horizontal, 12px vertical (extra side room for pill geometry)
- **Placeholder:** body color (#666666)
- **Transition:** all properties, 200ms

## Label

- Display: block
- Font: 14px, 500 (medium) weight, Open Sans, heading color (#000000)
- Margin bottom: 8px
- Label `htmlFor` must match the input `id`

## States

### Default

- Border: border-default-medium (#E5E7EB)
- Background: neutral-secondary-medium (#F5F5F5)

### Hover

- Border: border-default-strong (#E5E7EB)

### Focus

- No outline
- Border: border-brand (#000000)
- Ring: 1px, brand color (#000000)

### Success

- Border: border-success (#000000)
- Focus ring: 1px, success color (#000000)

### Error / Danger

- Border: border-danger (#000000)
- Focus ring: 1px, danger color (#000000)

### Disabled

- Background: disabled (#F5F5F5)
- Text: fg-disabled (#8F8F8F)
- Cursor: not-allowed

## Input with Icons

- Icon size: 16x16px
- Icon color: body (#666666)
- Container: relative positioned wrapper
- Start icon: absolutely positioned left, 16px left padding — input gets 44px left padding (extra to compensate for pill geometry)
- End icon: absolutely positioned right, 16px right padding — input gets 44px right padding
- Icons vertically centered within the wrapper

## Rules

- Every input must have a unique `id`
- Every label must have a matching `htmlFor`
- Padding: 20px horizontal, 12px vertical unless overridden for icon variants
- No arbitrary hex or hardcoded colors
- All inputs use 9999px pill radius — no square or reduced-radius variants

---

## Source file: `layout.md`

# Layout & Spacing

## Spacing Rhythm

Base unit: **8px**. All spacing values should be multiples of 8px.

| Context                                    | Value        |
| ------------------------------------------ | ------------ |
| Section vertical padding                   | 96px         |
| Minimum vertical gap between page sections | 64px         |
| Section header → content                   | 48px or 64px |
| Heading → paragraph                        | 16px         |
| Container horizontal padding               | 24px         |
| Flex/grid row gap                          | 16px         |
| Card grid gap                              | 24px         |
| Wide component grid gap                    | 32px         |
| Column layout gap                          | 48px         |

## Container

Standard section container: max-width 1152px, centered, 24px horizontal padding.

Every major section wraps content in this container.

## Content Composition Order

Inside each section, follow this order:

1. Heading (`h1`–`h3`)
2. Leading paragraph
3. Normal paragraph(s)
4. Lists, CTA links, or component grids

## Section Pattern

Each section has:

- 96px vertical padding
- A solid #FFFFFF background — every page section stays white wall-to-wall
- A centered container (max-width 1152px, 24px horizontal padding)
- A section header area with 48px bottom margin
- Section content below

The footer is the only block that breaks this rule: footer background uses brand (#000000) with white text inside.

## Motion & Animation

- Prefer CSS-native: `transition`, `animation`, `@keyframes`. Use a JS motion library only when CSS cannot achieve the behavior.
- Prioritize high-impact orchestrated moments over scattered micro-interactions. A single well-sequenced page-load animation using staggered `animation-delay` delivers more perceived quality than many isolated effects.
- Reserve scroll-triggered and hover transitions for moments that reinforce hierarchy or reward attention.

## Backgrounds & Visual Depth

- Default to a flat #FFFFFF canvas — no gradients, no noise textures, no decorative meshes on the core UI.
- Depth is communicated through whitespace, the single 1px #E5E7EB hairline, and the contrast between #FFFFFF (page) and #F5F5F5 (surface card).
- Color may only enter the page through editorial photography or imagery sitting inside cards — never through UI fills, button color, or section backgrounds.
- Every decorative element must serve a compositional purpose (separation or emphasis). No purely ornamental effects competing with content.

## Must

- All sections: consistent 96px vertical padding, with a minimum 64px vertical gap between sibling sections
- All containers: max-width 1152px, centered, 24px horizontal padding
- Section headers: 48px or 64px bottom margin
- Page background is always #FFFFFF; only the footer uses #000000
- Consistent vertical rhythm, no crowded sections
- Layouts readable and properly spaced on both desktop and mobile

---

## Source file: `lists.md`

# Lists

> Dependencies: `colors.md`

## Core Specs

- Item spacing: 16px vertical gap between list items
- Text: body color (#666666)
- Font: Open Sans, 16px, 400 (regular) weight

## List Icons

- Size: 20x20px
- Prevent squishing: no shrink
- Spacing: 8px right margin between icon and text
- Active/featured icon: fg-brand color (#000000)
- Neutral icon: body color (#666666)

## Inactive / Disabled Items

Strikethrough text in body-subtle color (#8F8F8F) on the list item.

## Pattern

Vertical flex list with 16px gap. Each item is a flex row with centered alignment — icon (20x20, no-shrink, 8px right margin) followed by a span of body-colored text.

---

## Source file: `modals.md`

# Modals

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `buttons.md`, `inputs.md`

## Core Specs

### Overlay (Backdrop)

- Fixed, covers full screen
- Z-index: 40
- Background: black (#000000) at 50% opacity
- Backdrop blur: small amount

### Content Container

- Background: neutral-primary (#FFFFFF)
- Radius: 6.08px (modal panels are content surfaces, not pills — they use the precise image-card radius)
- Shadow: none — separation from the page comes entirely from the backdrop scrim
- Padding: 24px

## Anatomy

### Header

- Bottom border: border-default (#E5E7EB)
- Top corners rounded (6.08px)
- Title: 22px, 600 (semibold) weight, heading color (#000000), -0.03em letter-spacing
- Close button: Ghost variant from `buttons.md`, 6px padding (rendered as a 9999px circle since the ghost button inherits pill geometry)

### Body

- Vertical padding: 24px
- Vertical spacing between elements: 24px
- Text: 16px, 1.6 line-height, body color (#666666), 0 letter-spacing

### Footer

- Top border: border-default (#E5E7EB)
- Bottom corners rounded (6.08px)
- Footer buttons follow `buttons.md` (9999px pill radius)

## Variants

### Default (Information)

Standard header + body + footer with primary/secondary action buttons.

### Pop-up (Confirmation)

Centered text, prominent icon, reduced padding:

- Body: 24px padding, text centered
- Icon: centered, 16px bottom margin, 48x48px, gray color (#666666)

### Form Modal

Body contains inputs following `inputs.md`. Vertical spacing between form elements: 16px.

## Rules

- Backdrop covers full screen with fixed positioning
- Content: neutral-primary (#FFFFFF) background, 6.08px radius, NO shadow
- Header/Footer separated by border-default (#E5E7EB) borders
- Close button must be present and functional, rendered as a 9999px ghost pill/circle
- Accessibility: `role="dialog"`, implement focus trap in code
- Dark mode automatic via token system

---

## Source file: `pagination.md`

# Pagination

> Dependencies: `colors.md`, `radius.md`

## Container

Font: 14px, Open Sans. Items displayed as flex with 4px gap between independent pill items (no overlapping borders — every page item is its own pill).

## Pagination Item

- Layout: flex, centered both axes
- Size: 36x36px (or 40x40px) — square aspect ratio so a 9999px radius produces a circle
- Text: body color (#666666), 500 (medium) weight
- Background: neutral-secondary-medium (#F5F5F5)
- Border: 1px, border-default-medium (#E5E7EB)
- Radius: 9999px (every item is a circular pill)
- Hover: neutral-tertiary-medium background (#F5F5F5), heading text (#000000)
- Focus: no outline, 2px ring in brand color (#000000)
- Spacing: 4px gap between items

## Previous / Next Buttons

- Horizontal padding: 16px, height: 36px
- Radius: 9999px on all corners (full pill — these are not segmented end caps)
- Background: neutral-secondary-medium (#F5F5F5)
- Border: 1px, border-default-medium (#E5E7EB)

## Active Page Item

- Text: white
- Background: brand (#000000)
- Border: transparent
- Hover text: white (stays same)

## Rules

- Display as flex with 4px gap between items — items do NOT overlap; each is an independent pill
- Items: neutral-secondary-medium background (#F5F5F5), border-default-medium border (#E5E7EB), body text (#666666)
- Active: white text, black (#000000) background — the only filled state
- Every item uses 9999px radius — no segmented bar with shared end caps
- All items need hover and focus states
- No box-shadows on any item

---

## Source file: `radios-checkboxes-toggle.md`

# Radios, Checkboxes & Toggles

> Dependencies: `colors.md`, `radius.md`

## Checkbox

- Size: 16x16px
- Radius: 4px (the only sub-pixel exception in the system — kept tiny so the check glyph reads cleanly; do not enlarge)
- Border: 1px, border-default-medium (#E5E7EB)
- Background: neutral-secondary-medium (#F5F5F5)
- Focus ring: 2px, brand-soft (#F5F5F5) with 1px #000000 outline
- Checked: brand background (#000000), white check glyph

### Disabled

- Border: border-light (#E5E7EB)
- Text: fg-disabled (#8F8F8F)

## Radio

- Size: 16x16px
- Radius: 9999px (fully rounded)
- Border: 1px, border-default-medium (#E5E7EB)
- Background: neutral-secondary-medium (#F5F5F5)
- Focus ring: 2px, brand-soft (#F5F5F5) with 1px #000000 outline
- Checked: border-brand (#000000), indicator: neutral-primary color (#FFFFFF) on a brand (#000000) inner dot

### Disabled

- Border: border-light-medium (#E5E7EB)
- Text: fg-disabled (#8F8F8F)

Group all radio items under the same `name` attribute.

## Toggle

### Track

- Fully rounded (9999px)
- Background: neutral-quaternary (#E5E7EB)
- Focus-within ring: 2px, brand-soft (#F5F5F5) with 1px #000000 outline
- Checked track: brand background (#000000)
- Disabled track: neutral-tertiary background (#F5F5F5)

### Thumb

- Fully rounded (9999px)
- Background: white (#FFFFFF)
- Border: 1px border-buffer (#FFFFFF) — effectively flush; no box-shadow

### Disabled

- Track: neutral-tertiary background (#F5F5F5)
- Label: fg-disabled text (#8F8F8F)

## Rules

- All selection inputs must have `id` matching label `htmlFor`
- Focus states use the appropriate brand token (#000000) for each control type
- Disabled states: no hover/focus interaction
- No shadows on any selection control — separation comes from the track/thumb contrast and the 1px hairline

---

## Source file: `radius.md`

# Border Radius

| Token   | Value  | Default usage                                                                        |
| ------- | ------ | ------------------------------------------------------------------------------------ |
| card    | 24px   | **All cards** — every card and card-like container uses 24px only                    |
| base    | 9999px | Buttons, alerts, badges, inputs, modals, sections, pill chips, conversational fields |
| default | 9999px | Same as base — pill geometry for interactive controls                                |
| sm      | 6.08px | Checkboxes, tiny non-pill elements only — never used on cards                        |
| full    | 9999px | Pills, avatars, toggles, dot indicators                                              |

## Rules

- **Cards:** every card must use **24px border radius only** — no pill cards, no 6.08px image-card variant, no mixed radii within a card boundary
- **Buttons, alerts, badges, and inputs:** must always use **9999px pill** border radius — no square or reduced-radius variants
- Never use arbitrary radius values outside this scale
- Radius must be consistent within each component family
- Do not apply pill (9999px) radius to cards; do not apply card (24px) radius to buttons, alerts, badges, or inputs

---

## Source file: `shadows.md`

# Shadows

| Token      | CSS value |
| ---------- | --------- |
| shadow-2xs | `none`    |
| shadow-xs  | `none`    |
| shadow-sm  | `none`    |
| shadow-md  | `none`    |
| shadow-lg  | `none`    |
| shadow-xl  | `none`    |
| shadow-2xl | `none`    |

## Component Mapping

| Component type                                     | Token             |
| -------------------------------------------------- | ----------------- |
| Subtle separators, tiny UI details                 | shadow-2xs (none) |
| Inputs, buttons, small controls, lightweight cards | shadow-xs (none)  |
| Standard cards, popovers, dropdowns                | shadow-md (none)  |
| Prominent cards, sticky surfaces                   | shadow-lg (none)  |
| Modals, high-priority overlays                     | shadow-xl (none)  |
| Hero overlays, top-level emphasis (sparingly)      | shadow-2xl (none) |

## Rules

- All cards and buttons have NO shadow — separation comes from whitespace, not depth
- Do not apply box-shadows to cards under any circumstance
- Do not apply box-shadows to buttons, ghost buttons, or pill buttons
- Use only these tokens — no custom box-shadow values
- The system is intentionally flat: depth is communicated through generous whitespace, the #E5E7EB hairline border, and the contrast between #FFFFFF page surface and #F5F5F5 surface cards
- The only acceptable elevation cue is the modal/overlay backdrop scrim, never a drop shadow on the modal panel itself

---

## Source file: `sidebars.md`

# Sidebars

> Dependencies: `colors.md`, `radius.md`, `typography.md`, `badges.md`, `alerts.md`

## Core Specs

- Background: neutral-primary-soft (#FFFFFF)
- Right border: 1px, border-default (#E5E7EB) for left-sidebar; left border for right-sidebar
- Width: 256px
- Shadow: none

## Anatomy

### Outer Container

Hidden on mobile, visible at small breakpoint. Needs a toggle/trigger for mobile.

### Inner Wrapper

- Full height, vertical scroll overflow
- Padding: 16px horizontal, 20px vertical

### Navigation List

- Vertical spacing: 4px between items
- Font weight: 500 (medium), Open Sans

### Navigation Item

- Layout: flex, vertically centered
- Padding: 16px horizontal, 10px vertical
- Text: heading color (#000000)
- Radius: 9999px (every nav row is a pill — even when full-width)
- Hover: neutral-secondary-medium background (#F5F5F5)
- Transition: colors
- Icon: 20x20px, body color (#666666), hover → heading color (#000000), 75ms transition
- Label: 12px left margin from icon

### Active Item

- Background: neutral-secondary-medium (#F5F5F5)
- Text: heading (#000000)
- Optional 1px border in border-default (#E5E7EB)

### Separator

- 16px top padding, 16px top margin
- Top border: border-default (#E5E7EB)
- 8px vertical spacing below

### Bottom CTA / Card

- Padding: 16px
- Top margin: 24px
- Radius: 6.08px (this is a content card, not a pill row)
- Background: brand-softer (#FAFAFA) or neutral-secondary-medium (#F5F5F5)
- No shadow
- Can also use any alert variant from `alerts.md`

## Rules

- Responsive: hidden on mobile with a trigger mechanism
- Icons: 20x20px, body color (#666666); hover: heading color (#000000)
- Multi-level menus: indent with 44px left padding
- Spacing follows 8px grid
- Only neutral, brand (black), or status tokens — no arbitrary colors
- No box-shadows anywhere in the sidebar — depth comes from the 1px #E5E7EB rail and the surface tone

---

## Source file: `tables.md`

# Tables

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Wrapper

- Horizontal scroll overflow
- Background: neutral-primary-soft (#FFFFFF)
- Radius: 6.08px (table panels are content surfaces, not pills)
- Border: 1px, border-default (#E5E7EB)
- Shadow: none

## Table Element

- Full width, left-aligned text (right-aligned for RTL)
- Font: 14px, body color (#666666), Open Sans

## Table Head

- Font: 12px, body-subtle color (#8F8F8F), 500 (medium) weight, uppercase, +0.011em letter-spacing
- Background: neutral-secondary-soft (#FFFFFF) — header is flush with the table surface, separated only by the bottom border
- Bottom border: border-default (#E5E7EB)
- Cell padding: 24px horizontal, 16px vertical

## Table Body

- Row background: neutral-primary (#FFFFFF)
- Row bottom border: border-default (#E5E7EB) — omit on last row to avoid doubling with wrapper border
- Row hover: neutral-secondary-soft background (#F5F5F5) (optional)
- Row header: 500 (medium) weight, heading color (#000000), no-wrap
- Cell padding: 24px horizontal, 16px vertical

## Rules

- Wrapper must have horizontal scroll overflow for responsive scrolling
- Last row: omit bottom border to avoid doubling with wrapper border
- Row headers: always `scope="row"` for semantic structure
- Hover on rows is optional and uses #F5F5F5 only
- No arbitrary hex codes — use token colors only
- No shadows on the wrapper or rows; the table reads flat

---

## Source file: `tabs.md`

# Tabs

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Core Specs

- Typography: 14px, 500 (medium) weight, body color (#666666), Open Sans
- Transitions: all properties, 200ms

## Variants

### 1. Underline (Default)

**Wrapper:** bottom border, border-default (#E5E7EB)

**Tab Item:**

- Padding: 16px horizontal, 16px vertical
- Bottom border: 2px, transparent
- Top corners: 9999px (pill cap on the active tab)
- Transition: colors, 150ms

| State    | Appearance                                                                                               |
| -------- | -------------------------------------------------------------------------------------------------------- |
| Active   | heading text (#000000), border-brand bottom border (#000000)                                             |
| Inactive | transparent bottom border; hover → heading text (#000000), border-default-strong bottom border (#E5E7EB) |
| Disabled | fg-disabled text (#8F8F8F), not-allowed cursor                                                           |

### 2. Pills

**Tab Item:**

- Padding: 16px horizontal, 10px vertical
- Radius: 9999px (full pill)
- Font weight: 500 (medium)
- Transition: all, 200ms
- Shadow: none

| State    | Appearance                                                                                       |
| -------- | ------------------------------------------------------------------------------------------------ |
| Active   | brand background (#000000), white text, NO shadow                                                |
| Inactive | body text (#666666); hover → neutral-secondary-soft background (#F5F5F5), heading text (#000000) |
| Disabled | fg-disabled text (#8F8F8F), not-allowed cursor                                                   |

### 3. Full Width

Children sit in a row with 4px gap; each tab is its own pill (no overlapping borders).

**Tab Item:**

- Full width within its segment, centered text
- Padding: 16px horizontal, 14px vertical
- Background: neutral-primary-soft (#FFFFFF)
- Border: 1px, border-default (#E5E7EB)
- Radius: 9999px (every tab is its own pill)
- Transition: colors, 150ms
- Hover: neutral-secondary-medium background (#F5F5F5), heading text (#000000)

| State             | Appearance                                                  |
| ----------------- | ----------------------------------------------------------- |
| Active            | brand background (#000000), white text                      |
| First / Last item | 9999px radius (same as every other tab; full-pill segments) |

## Tabs with Icons

- Icon size: 16x16px or 20x20px
- Spacing: 8px right margin
- Layout: inline-flex, centered
- Icons inherit the text color of the tab state

---

## Source file: `tooltips-popovers.md`

# Tooltips & Popovers

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Tooltips

### Core Specs

- Padding: 12px horizontal, 8px vertical
- Font: 14px, 500 (medium) weight, Open Sans
- Radius: 9999px (tooltips are pills in this system — they read as floating chips)
- Shadow: none — separation comes from the contrasting background tone alone
- Transition: opacity, 300ms

### Dark (Default)

- Background: dark (#000000)
- Text: white (#FFFFFF)
- Border: transparent

### Light

- Background: neutral-primary-medium (#FFFFFF)
- Text: heading color (#000000)
- Border: 1px, border-default (#E5E7EB)

## Popovers

### Core Specs

- Background: neutral-primary (#FFFFFF)
- Radius: 6.08px (popovers are content surfaces — they use the precise image-card radius, not the pill radius)
- Shadow: none
- Border: 1px, border-default (#E5E7EB)
- Transition: opacity, 300ms

### Header / Title

- Padding: 12px horizontal, 8px vertical
- Background: neutral-secondary-soft (#FFFFFF)
- Bottom border: border-default (#E5E7EB)
- Font: 14px, 500 (medium) weight, heading color (#000000)

### Body / Content

- Standard: 12px horizontal, 8px vertical padding; 14px, body color (#666666)
- Rich: 16px padding; 14px, body color (#666666)

## Arrows

- Size: 8x8px rotated 45deg
- Color must match the background of the tooltip/popover variant
- For pill-shaped tooltips, the arrow is optional — many pill tooltips read better without an arrow

## Rules

- Tooltips: 9999px radius (pill geometry)
- Popovers: 6.08px radius (content-surface geometry)
- Dark tooltips: dark (#000000) background, white text — the only place dark fill is used outside of buttons and the footer
- Light tooltips/popovers: semantic neutral background + 1px #E5E7EB border tokens
- Arrows match parent background color
- No box-shadows on either component

---

## Source file: `typography.md`

# Typography

> Dependencies: `colors.md`

## Core Rules

- **Font:** Open Sans, sans-serif — configured at app level, never override. Load from Google Fonts (https://fonts.google.com/specimen/Open+Sans) and use weights 400, 500, 600 only
- **Headings:** semibold weight (600), heading text color (#000000)
- **Body copy:** body text color (#666666), never use brand color for paragraphs longer than one sentence
- **Semantic HTML:** Use `h1`–`h6` in order, never skip levels
- **Weight discipline:** never go below 400 or above 600 — the 400/500/600 triad defines the entire typographic hierarchy

## Heading Scale

### Desktop

| Element | Size | Line-height | Letter-spacing | Margin-bottom |
| ------- | ---- | ----------- | -------------- | ------------- |
| `h1`    | 48px | 1           | -0.03em        | 24px          |
| `h2`    | 40px | 1.1         | -0.03em        | —             |
| `h3`    | 32px | 1.15        | -0.03em        | —             |
| `h4`    | 26px | 1.2         | -0.03em        | —             |
| `h5`    | 22px | 1.3         | —              | —             |
| `h6`    | 20px | 1.35        | —              | —             |

### Responsive

| Element | Tablet (≥768px) | Mobile (default) |
| ------- | --------------- | ---------------- |
| `h1`    | 36px            | 30px             |
| `h2`    | 32px            | 26px             |
| `h3`    | 28px            | 24px             |
| `h4`    | 24px            | 22px             |
| `h5`    | 22px            | 20px             |
| `h6`    | 18px            | 18px             |

Mobile-first: start with mobile sizes, scale up at tablet and desktop breakpoints.

Never reduce line-height below 1 for any heading.

Letter-spacing of -0.03em is reserved for display text at 22px and above. Do NOT apply tracking overrides below 22px unless using all-caps labels.

## Paragraphs

### Leading Paragraph

- Size: 18px
- Weight: 400 (regular)
- Color: body (#666666)
- Line-height: 1.6
- Letter-spacing: 0 (no tracking at body sizes)
- Max width: ~70 characters

### Normal Paragraph

- Size: 16px
- Weight: 400 (regular)
- Color: body (#666666)
- Line-height: 1.6
- Letter-spacing: 0 (no tracking at body sizes)
- Max width: ~65 characters

### Small Supporting Copy

- Size: 14px
- Weight: 400 (regular)
- Color: body (#666666)
- Line-height: 1.5
- Letter-spacing: 0
- Use only for helper text, legal text, captions, metadata.

## UI Labels

| Context                  | Size         | Weight       |
| ------------------------ | ------------ | ------------ |
| Button labels            | 16px         | 500 (medium) |
| Input labels             | 14px or 16px | 500 (medium) |
| Captions / meta / badges | 12px or 14px | 500 (medium) |

Do not apply paragraph line-height (1.6) to control labels.

## Links

- **Inline links:** Same size as surrounding text, fg-brand color (#000000), underline, hover → no underline
- **CTA links:** fg-brand color (#000000), 500 (medium) weight, underline, hover → no underline

## Emphasis

- `<strong>` for high-priority emphasis in body text — uses 600 weight
- `<em>` for tone emphasis only, not visual hierarchy
- All-caps only for short labels: uppercase, +0.011em letter-spacing, 12px or 14px, 500 weight
- Use no more than two typographic colors at once: #000000 (heading) for primary and #666666 (body) for secondary; #8F8F8F is reserved exclusively for disabled or tertiary metadata — never for prose

## Dark Mode

Hierarchy stays identical. Only color tokens change (automatic via CSS custom properties). Size, weight, and spacing remain constant.
