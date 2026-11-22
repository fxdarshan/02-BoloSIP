---
name: Luminous Ledger
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#3d4a42'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#6d7a72'
  outline-variant: '#bccac0'
  surface-tint: '#006c4a'
  primary: '#006948'
  on-primary: '#ffffff'
  primary-container: '#00855d'
  on-primary-container: '#f5fff7'
  inverse-primary: '#68dba9'
  secondary: '#565e74'
  on-secondary: '#ffffff'
  secondary-container: '#dae2fd'
  on-secondary-container: '#5c647a'
  tertiary: '#006194'
  on-tertiary: '#ffffff'
  tertiary-container: '#007bb9'
  on-tertiary-container: '#fdfcff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#85f8c4'
  primary-fixed-dim: '#68dba9'
  on-primary-fixed: '#002114'
  on-primary-fixed-variant: '#005137'
  secondary-fixed: '#dae2fd'
  secondary-fixed-dim: '#bec6e0'
  on-secondary-fixed: '#131b2e'
  on-secondary-fixed-variant: '#3f465c'
  tertiary-fixed: '#cce5ff'
  tertiary-fixed-dim: '#93ccff'
  on-tertiary-fixed: '#001d31'
  on-tertiary-fixed-variant: '#004b73'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Inter
    fontSize: 26px
    fontWeight: '700'
    lineHeight: 34px
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.005em
  body-lg:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.02em
  mono-metric:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: -0.01em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.25rem
  margin: 1rem
  margin-desktop: 1.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style
This design system defines a luminous, high-precision financial terminal aesthetic designed for regulatory compliance, data clarity, and cognitive ease under analytical workloads. It balances institutional rigor with an airy, porcelain-like lightness. 

The aesthetic is Modern Financial Precision: clean, architectural, and legible. It strips away noisy ornamentation in favor of crisp micro-borders, translucent tinted indicator pills, and disciplined structural hierarchies. The interface evokes trust, analytical speed, and composure, replacing the visual fatigue of traditional dense dark terminals with an immaculate daylight workstation.

## Colors
The palette balances porcelain canvas tiers with authoritative navy-slate typography and a vibrant emerald core.

- **Base Surfaces**: The workspace utilizes layered off-white tones—`#F8F9FA` for window backgrounds, `#FFFFFF` for elevated data panels and analytical cards, and `#EEF2F6` for input tracks, recessed toolbars, and inactive segments.
- **Typography & Structure**: Deep navy-slate (`#0F172A`) commands primary metrics and headlines, while medium slate (`#334155`) supports body copy, metadata, and labels. Structural lines utilize a razor-sharp border stroke (`#E2E8F0`).
- **Accent**: Emerald (`#059669` primary interactive, `#10B981` highlight) drives transactional commitments, positive delta yields, and active states.
- **Semantic Badges & Indicators**:
  - *Facts / Verified Yield*: Tinted Mint (`#ECFDF5` background, `#059669` text, `#A7F3D0` border).
  - *Statutory Guardrails / Rules*: Soft Sky (`#F0F9FF` background, `#0284C7` text, `#BAE6FD` border).
  - *Privacy Safeguards / Redactions*: Soft Rose/Coral (`#FFF1F2` background, `#E11D48` text, `#FECDD3` border).
  - *Disambiguation / Warnings*: Warm Amber (`#FFFBEB` background, `#D97706` text, `#FDE68A` border).
  - *Information Horizon / Pending*: Muted Slate (`#F1F5F9` background, `#475569` text, `#CBD5E1` border).

## Typography
The system uses Inter across all viewports to preserve optical clarity for high-density tabular numerical data and textual directives. 

Tabular figures (`font-variant-numeric: tabular-nums`) must be enabled across all financial tables, execution logs, and timestamp displays to eliminate visual jitter during ticker updates. Metric figures utilize medium and semi-bold weights with tightened tracking for cohesive data scanning, while micro labels apply subtle positive tracking for instantaneous semantic grouping.

## Layout & Spacing
The layout follows a 12-column responsive fluid grid designed to host multi-pane financial workspaces, blotters, and analytical inspector sidebars.

- **Desktop (1280px+)**: 12-column grid with 20px (`1.25rem`) gutters and 24px (`1.5rem`) outer canvas margins. Multi-column density allows simultaneous observation of conversation logs, statutory policy breakdowns, and real-time execution cards.
- **Tablet (768px - 1279px)**: 8-column layout with 16px (`1rem`) gutters. Sidebars fold into sliding overlays or collapsible vertical split-views.
- **Mobile (< 768px)**: 4-column layout with 16px (`1rem`) margins and gutters. Financial actions, filter trays, and badged streams stack vertically into full-width sequential flows.

## Elevation & Depth
Depth in this system avoids heavy, dark drop-shadows, relying instead on structural boundaries and clean, diffuse ambient offsets:

- **Level 0 (Canvas Surface)**: `#F8F9FA` base with no elevation.
- **Level 1 (Docked Panels & Cards)**: `#FFFFFF` surface framed by a 1px border stroke (`#E2E8F0`) paired with a micro-ambient shadow: `0 1px 3px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.02)`.
- **Level 2 (Active Focus & Flyouts)**: Elevated interactive elements cast an ambient diffuse shadow: `0 4px 12px rgba(15, 23, 42, 0.06), 0 2px 4px rgba(15, 23, 42, 0.03)` with a hairline `#E2E8F0` edge.
- **Level 3 (Modals & Regulatory Overlays)**: High-prominence dialogs utilize `0 20px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04)` over a faint frosted backdrop blur (`rgba(248, 249, 250, 0.8)` with `backdrop-filter: blur(4px)`).

## Shapes
The shape language implements an 8px (`0.5rem`) base corner radius throughout standard interaction points.

Standard cards, containers, input frames, and action buttons strictly adhere to the 8px specification, balancing modern softness with financial geometry. Smaller interior elements such as semantic response tags, pill badges, and table cell statuses use standard 4px or pill-shaped radii where distinct encapsulation is required.

## Components

- **Buttons**:
  - *Primary*: `#059669` fill with crisp white text (`#FFFFFF`), 8px border radius, 8px 16px padding. Active state darkens to `#047857`. Hover introduces a subtle top-lit inner highlight.
  - *Secondary / Neutral*: `#FFFFFF` surface with `#E2E8F0` border and `#334155` text. On hover, background shifts to `#EEF2F6`.
  - *Ghost / Minimal*: Transparent background, `#334155` text, shifting to `#EEF2F6` on hover.

- **Semantic Reply Badges (Chips)**:
  - Formed with a 6px or fully pill radius, 2px 8px padding, typography set to `label-sm`.
  - *Facts*: Background `#ECFDF5`, text `#059669`, border 1px solid `#A7F3D0`.
  - *Statutory Guardrails*: Background `#F0F9FF`, text `#0284C7`, border 1px solid `#BAE6FD`.
  - *Privacy Safeguards*: Background `#FFF1F2`, text `#E11D48`, border 1px solid `#FECDD3`.
  - *Disambiguation*: Background `#FFFBEB`, text `#D97706`, border 1px solid `#FDE68A`.
  - *Info Horizon*: Background `#F1F5F9`, text `#475569`, border 1px solid `#CBD5E1`.

- **Cards & Terminal Panels**:
  - Constructed on `#FFFFFF` with an 8px radius and a continuous 1px `#E2E8F0` border stroke. Headers within cards feature a baseline border divider (`#E2E8F0`) with uppercase subtext in `label-sm` (`#64748B`).

- **Input Fields & Search**:
  - Background `#FFFFFF` or `#EEF2F6` (recessed query modes), border 1px solid `#E2E8F0`, 8px radius. Active focus transitions border to `#059669` with a soft mint focus halo (`box-shadow: 0 0 0 3px rgba(5, 150, 105, 0.15)`).

- **Checkboxes & Radios**:
  - 16px square (or circle) with an 8px radius or rounded-full profile. Border 1.5px solid `#CBD5E1`. Selected state filled with `#059669` containing an optical white checkmark or center pip.

- **Data Tables & Blotters**:
  - Clean edge-to-edge layout with alternating or consistent white rows divided by 1px horizontal `#E2E8F0` rules. Table header cells employ `#F8F9FA` background, semi-bold `label-sm` text in `#64748B`, and hoverable sort states. Numeric data aligns right using `mono-metric` styling.