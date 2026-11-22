# BoloSIP UI: review of the Google Stitch design and what was built

> **Facts-only. No investment advice.**

20 Nov 2026 · Input: Google Stitch export `stitch_bolosip_mutual_fund_assistant.zip` (7 screens, 2 design-system notes), generated from the prompt in this conversation · Output: [`web/index.html`](../../web/index.html) (Phase 6)

The Stitch screens and design notes are kept for reference in [`stitch/`](stitch/). They are a **reference, not the build**: the build is the single file `web/index.html`, made to the rules in [architecture.md](../architecture.md) §14.

## 1. What was kept

| From Stitch | In the build |
|---|---|
| "Calm Financial Terminal" dark palette (`#111319` canvas, `#1d2025` cards, mint `#3dd6a3` accent) | Dark theme, the default |
| "Luminous Ledger" light palette (`#f8f9ff` canvas, emerald `#006c4e`) | Light theme, from the header toggle (remembered in the browser) |
| Welcome screen: big icon, headline, 3 example cards with big icon tiles and a category label | Same, with the welcome text and examples taken from `/api/config` |
| One card per reply type: big icon in a tinted tile, coloured left accent, uppercase label | Same for all 7 kinds (answer, refusal, performance, privacy, clarify, not found, help) |
| Highlighted values ("0.73% per annum") | Percentages, ₹ amounts and quoted riskometer levels are highlighted, still drawn as plain text |
| Source chip with an external-link icon, clock icon on the footer | Same |
| Clarify choices as large buttons with an arrow | Same; a choice sends "scheme name + the topic you asked about" |
| Delete confirmation inside the thread list, typing indicator, rate-limit toast | Same |

## 2. What was wrong, and the fix

### Visual consistency (the reported problem)

| Problem in the Stitch output | Fix |
|---|---|
| **Thick light borders on mobile**: cards, buttons and drawer items drew 2px borders in the light-grey `outline` colour (`#85948c`), so on the dark canvas every element had a white ring. Desktop used faint 1px lines, so the two looked like different products | One component set for every width. Every border is a 1px hairline at ≤ 18% opacity (`--line`, `--line-strong`); depth comes from surface steps (canvas → panel → card → raised card). A test forbids borders thicker than 1px |
| **Mobile conversation lost the replies**: only user bubbles rendered, with large empty gaps | Replies use the same card on mobile; the icon and label move into a header row so the text gets the full width |
| **Mobile header overflowed**: the "Research engine" pill wrapped, the rate-limit badge overlapped its text | Header row: menu, logo, theme. The disclaimer gets its own full-width row below it, still inside the sticky header |
| **Broken logo**: an `<img>` pointing at a Google-hosted file that doesn't load ("BoloSIP Logo" alt text shown) | Inline SVG mark (speech bubble with rising SIP bars) and wordmark; also the favicon |
| Light-grey "faint" text at 4.0:1 on raised cards | Raised to `#8d9893` (≥ 4.8:1). A test checks every text and icon colour against WCAG AA (4.5:1) in both themes |
| Drawer focus scrolled the page sideways while sliding in | Focus without scrolling; no horizontal scroll at 375 px |

### Content that BoloSIP cannot claim

The draft added badges and copy that are not true for this project. Showing them would mislead users about regulation and freshness, so all were removed, and a test keeps them out:

- "SEBI-compliant fact retrieval", "Mandatory SEBI guardrail", "SEBI filing compliant"
- "AMFI live feed: active / synced", "SID / KIM data: Q4 Oct 2024 verified", "Verified snapshot v4.8", "Fact checked"
- "Research engine", "AI engine", "Zero commission / non-distributor"
- a user avatar (there are no accounts)
- sample threads about other fund houses and returns ("Parag Parikh vs HDFC", "SBI Small Cap 5Y CAGR"), which BoloSIP refuses
- sources that don't match the corpus (an exit-load answer citing an "SID / factsheet": BoloSIP cites the Groww scheme page)
- the user's PAN echoed in a chat bubble. In the build, after a privacy reply the thread is re-drawn from the server, which stored `[redacted]`

The sidebar instead says what the sources really are: the Groww pages of the 27 schemes and official HDFC MF, AMFI and SEBI pages, each answer with its own date.

### Rules from the architecture

| Stitch output | Rule | Build |
|---|---|---|
| Tailwind CDN script, Google Fonts (Inter), Material Symbols icon font | No external scripts, fonts or trackers (arch §14); the server's Content-Security-Policy allows only same-origin | Inline CSS; system font stack (Inter where installed); 25 inline SVG icons drawn with `createElementNS` |
| Markup templates with `innerHTML` | All message text via `textContent` (UI-01) | No `innerHTML` anywhere (tested); a `<script>` or `onerror` payload is shown as text |
| Design notes mention CAGR, yields and "positive deltas" | No returns figures (rule 3) | Not used |

## 3. Result

| Check (20 Nov 2026, built-in Chromium, 1440 px and 375 px) | Result |
|---|---|
| Welcome, 3 examples and the disclaimer on first load; disclaimer visible while scrolling | Pass |
| Each example gives a cited, dated answer | Pass |
| All 7 reply kinds render correctly | Pass |
| XSS payloads shown as text | Pass |
| 375 px: no horizontal scroll, drawer works | Pass |
| Server down: friendly message, typed text kept | Pass |
| Clarify buttons resolve | Pass |
| Keyboard: every control reachable and labelled; replies announced (`aria-live`) | Pass |
| Two tabs, two threads: no interference | Pass |

Recorded in [`eval/manual/phase6_ui_check.json`](../../eval/manual/phase6_ui_check.json). Still to do by a person: the same check in Edge, a Lighthouse accessibility score (≥ 90), a screen-reader pass (NVDA or Narrator) and the 3-person usability check in [eval.md](../eval.md) §5.
