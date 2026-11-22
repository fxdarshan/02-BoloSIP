---
name: Calm Financial Terminal
colors:
  surface: '#111319'
  surface-dim: '#111319'
  surface-bright: '#36393f'
  surface-container-lowest: '#0b0e13'
  surface-container-low: '#191c21'
  surface-container: '#1d2025'
  surface-container-high: '#272a30'
  surface-container-highest: '#32353a'
  on-surface: '#e1e2e9'
  on-surface-variant: '#bbcac1'
  inverse-surface: '#e1e2e9'
  inverse-on-surface: '#2e3036'
  outline: '#85948c'
  outline-variant: '#3c4a43'
  surface-tint: '#48deab'
  primary: '#61f3be'
  on-primary: '#003827'
  primary-container: '#3dd6a3'
  on-primary-container: '#005840'
  inverse-primary: '#006c4e'
  secondary: '#9bcaff'
  on-secondary: '#003256'
  secondary-container: '#006cb0'
  on-secondary-container: '#dae9ff'
  tertiary: '#ffd57b'
  on-tertiary: '#3f2e00'
  tertiary-container: '#e8b846'
  on-tertiary-container: '#634900'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#6afbc6'
  primary-fixed-dim: '#48deab'
  on-primary-fixed: '#002115'
  on-primary-fixed-variant: '#00513a'
  secondary-fixed: '#d0e4ff'
  secondary-fixed-dim: '#9bcaff'
  on-secondary-fixed: '#001d35'
  on-secondary-fixed-variant: '#00497a'
  tertiary-fixed: '#ffdf9d'
  tertiary-fixed-dim: '#f0c04d'
  on-tertiary-fixed: '#251a00'
  on-tertiary-fixed-variant: '#5b4300'
  background: '#111319'
  on-background: '#e1e2e9'
  surface-variant: '#32353a'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  title-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '500'
    lineHeight: 26px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 25.6px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22.4px
  label-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-tablet: 1.5rem
  margin-desktop: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

## Brand & Style
The design system establishes a high-precision, conversational financial workspace crafted specifically for exploring mutual fund scheme data with zero ambiguity. The tone is deliberate, analytical, and reassuringly unhurried—delivering institutional clarity without regulatory pretense.

The visual style blends modern terminal utility with calm minimalism:
- Deep, low-fatigue slate backgrounds create an ergonomic canvas for extended financial inquiry.
- Crisp visual hierarchy relies on disciplined typographic weight and structured spatial grouping rather than decorative ornament.
- Zero decorative gradients behind analytical text ensure absolute legibility of figures, fund ratios, and historical yield data.
- Strict visual differentiation between objective scheme facts, user prompts, system disambiguation triggers, and regulatory advice refusals.

## Colors
The palette leverages a deep charcoal foundation with surgical semantic indicators to maintain strict WCAG AA contrast across all data views:

- **Canvas & Surface Architecture**:
  - Base canvas: `#0E1116`
  - Floating panels, chat logs, and side drawers: `#161B22`
  - Raised cards, metric panels, and popovers: `#1F2630`
  - Structural separators and stroke borders: `#2A3340`

- **Typography & Content Hierarchy**:
  - Primary text, metric values, and active headers: `#E6EDF3` (exceeds 12:1 contrast against base)
  - Secondary text, scheme categories, and metadata: `#9AA7B4` (exceeds 6:1 contrast against base)
  - Muted timestamps, subtle identifiers, and inactive borders: `#8B949E`

- **Interactive & Semantic Accents**:
  - **Mint Green (`#3DD6A3`)**: Reserved for system focus states, active button states, positive deltas, interactive links, and scheme verification marks.
  - **Advice Refusal Blue (`#6CB6FF`)**: Designates regulatory boundaries, educational guidance, and non-advisory statements where direct financial recommendation is intentionally declined.
  - **Warning / Privacy Coral (`#FF7B72`)**: Flags PII inputs, risk-level disclosures, high tracking errors, or session timeouts.
  - **Disambiguation Ochre (`#F2C14E`)**: Signals multiple matching schemes (e.g., Growth vs. IDCW, Direct vs. Regular), scheme mergers, or benchmark shifts.

## Typography
The system employs an authoritative, highly legible system-native sans-serif stack led by `Inter, system-ui, -apple-system, sans-serif`. 

Core reading metrics are tuned for uninterrupted scanning during chat interactions and complex data parsing:
- Base body copy is pinned to `16px` with a strict `1.6` proportional line-height (`25.6px`) to ensure rapid comprehension of dense mutual fund terms.
- Tabular figures (`font-variant-numeric: tabular-nums`) must be enforced for all NAV figures, expense ratios, AUM sums, and compound annual growth rates (CAGR).
- Labels and disclaimer badges leverage uppercase trackings with explicit vertical centering to balance compactness with legibility.

## Layout & Spacing
The layout adheres to a structured, fluid conversational container flanked by optional analytical side-sheets:

- **Breakpoints & Max Canvas**:
  - Mobile (`< 768px`): Full-width conversation stream with `1rem` safe-area canvas margins and compact card padding (`space-md`).
  - Tablet (`768px - 1024px`): Single centered thread capped at `720px` width with `margin-tablet` outer space.
  - Desktop (`> 1024px`): Split canvas featuring an `800px` primary conversational pane alongside a persistent `380px` scheme metric rail, separated by `gutter-desktop`.

- **Vertical Rhythm**:
  - Message bubble separation: `space-md` between conversational turns, `space-sm` between continuous system disclosures.
  - Form & metric grouping: Internal component padding strictly defaults to `space-md` (16px) or `space-lg` (24px).

## Elevation & Depth
Depth is constructed through tonal step-ups and crisp borders rather than diffuse, heavy shadows:

- **Surface Levels**:
  - Level 0 (Ground): `#0E1116` — base window canvas.
  - Level 1 (Panels): `#161B22` with a `1px` solid outline of `#2A3340` — conversational stream and persistent navigation.
  - Level 2 (Cards & Inset Overlays): `#1F2630` with `1px` solid border `#2A3340` — scheme data modules, NAV comparison cards, and user input fields.
  - Level 3 (Floating Menus & Disambiguation Popovers): `#1F2630` accompanied by a crisp hairline border (`#3DD6A3` at 20% alpha) and a subtle, dark ambient ground drop: `0 8px 24px rgba(0, 0, 0, 0.45)`.

- **Focus & Interaction Rings**:
  - Interactive elements employ a dual-ring focus state: a `2px` solid `#0E1116` underlay offset and a sharp `2px` outer ring in `#3DD6A3`.

## Shapes
Surfaces feature generous, welcoming corner radii to soften the institutional nature of financial disclosures while preserving precision:

- Interactive buttons, form inputs, and scheme message cards use standard rounded geometry (`0.75rem` to `1rem` / 12–16px).
- Small functional tags, chips, and disclaimer badges utilize a compact `0.5rem` radius (8px).
- Avatars, status pings, and scheme category pill filters maintain full curvature (`9999px`).

## Components

- **Buttons**:
  - *Primary*: Background `#3DD6A3`, text `#0E1116` (600 weight), radius `12px`, padding `10px 18px`. Hover: brightness 108%. Active: brightness 95%.
  - *Secondary / Ghost*: Background transparent, border `1px solid #2A3340`, text `#E6EDF3`. Hover: background `#1F2630`, border color `#3DD6A3`.
  - *Disambiguation Actions*: Background `rgba(242, 193, 78, 0.1)`, border `1px solid #F2C14E`, text `#F2C14E`.

- **Input Fields & Chat Bar**:
  - Fixed dock at container base, surface `#161B22`, inner input container `#1F2630` with `1px solid #2A3340`.
  - Placeholder `#8B949E`, active text `#E6EDF3`.
  - Height `48px`, border radius `12px`. Focus state transitions to `1px solid #3DD6A3`.

- **Scheme Information Cards**:
  - Container `#1F2630`, border `1px solid #2A3340`, radius `16px`, padding `16px`.
  - Top header row: Scheme name in `#E6EDF3` (`title-md`), category badge (`label-sm`) in `#161B22` on `#9AA7B4` background.
  - Metric grid: NAV, 1Y/3Y Returns, Expense Ratio, and Fund Manager displayed in structured 2-column key-value pairs with `#9AA7B4` keys and tabular `#E6EDF3` values.

- **Chips & Quick Prompts**:
  - Surface `#161B22`, border `1px solid #2A3340`, text `#9AA7B4`, radius `8px`, height `32px`.
  - Active/Hover: Text `#3DD6A3`, border `1px solid #3DD6A3`, background `rgba(61, 214, 163, 0.08)`.

- **System Callout / Advice Refusal Banner**:
  - Container `rgba(108, 182, 255, 0.08)`, border `1px solid #6CB6FF`, radius `12px`, padding `12px 16px`.
  - Inline refusal icon with message in `#E6EDF3` clarifying that direct stock advice or non-factual predictions are prohibited under regulatory mandates.

- **Facts-Only Disclaimer Badge**:
  - Compact badge with `rgba(139, 148, 158, 0.15)` fill, `#8B949E` border, text `#9AA7B4` (`label-sm`).
  - Prepended with a clean line-art shield icon indicating unopinionated AMFI/HDFC Mutual Fund sourced data.

- **Icons**:
  - Monoline stroke weight `1.75px`, box size `20x20px`, tinted contextually to adjacent text tokens (`#9AA7B4` default, `#3DD6A3` for validated actions).