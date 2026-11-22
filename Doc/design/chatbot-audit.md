# BoloSIP: chatbot design audit

> **Facts-only. No investment advice.**

22 Nov 2026 · Method: the 12 considerations of the `chatbot-flow-design` skill (rampstackco/claude-skills, installed in `~/.claude/skills`), applied to the built app (Phases 0–6). Changes made from it are listed with their tests.

## 1. The 12 considerations

| # | Consideration | BoloSIP before | Verdict / change |
|---|---|---|---|
| 1 | Is a chatbot the right tool? | Recurring factual questions about 27 schemes, grounded in a maintained corpus, success metrics defined in eval.md | ✅ Earns deployment |
| 2 | Structured, not scripted or hallucinating | Intent = scheme + topic resolution; extractive answers from retrieved facts; honest fallback | ✅ Structured-guided |
| 3 | Intent architecture, 70–90% coverage | 12 scheme topics × 27 schemes + 9 general topics; guards for advice, returns, personal data | ✅ Coverage measured by the eval sets. **Added typing suggestions** that steer users to phrasings known to work |
| 4 | Grounded answers | Every answer is a stored fact with its source and date; no generation | ✅ **Fixed one grounding gap**: stamp-duty synonyms ("government duty") |
| 5 | Branching adds value, 3–5 turns | Follow-ups by thread context; clarify for confusable names | ⚠️ An answer was a dead end. **Added "Ask next" chips** (the same scheme's other key facts, never repeating a topic already asked) |
| 6 | Multi-layered fallback | Clarify → not found with the closest official page | ⚠️ No "suggested intents" layer; a second miss looked the same as the first. **Added "Try instead" chips** after not found, refusals and returns questions, and **a capability note after two misses in a row** |
| 7 | Escalation triggers | — | ➖ No support team behind BoloSIP. The official page link (HDFC MF, AMFI, SEBI) is the hand-off; documented rather than faked |
| 8 | Escalation context hand-off | — | ➖ Not applicable (see 7) |
| 9 | Analytics instrumented | None | ⚠️ **Added `scripts/usage_report.py`**: reply mix per kind, fallback rate, answers per topic and scheme, threads with two misses in a row; question text only on request |
| 10 | Maintenance cadence | `python ingest.py` refreshes the 27 pages; every answer shows its date | ✅ Use the usage report's unanswered list to find gaps |
| 11 | Brand voice consistent | Fixed wording per reply kind; neutral, no judgement words (tested) | ✅ |
| 12 | Audience fit honest | Facts-only scope stated in the header, welcome and every refusal | ✅ |

## 2. Found while doing it

- **ISS-039 (fixed):** on the BM25 fallback, "bitcoin price" asked in a Mid Cap thread was answered with Mid Cap's NAV. An unrecognised question borrowed the thread's scheme and a keyword ("price") matched. Now the thread's scheme is used only with a follow-up signal (a pronoun, a named topic, an opening "and / also / what about", or a plan word), and a scheme taken from the thread with no named topic must clear the stricter no-scheme bar. Regression case CONV-28.
- **Suggestion ranking**, tuned against real typing: whole-word matches beat prefixes ("ter" is the expense ratio, not "Ultra Short **Ter**m"); scheme names beat topic synonyms ("small cap" is not "smallest amount"); words of the question template add a bonus ("who man" → "Who manages …"); duplicates removed.

## 3. What was added, and how it is checked

| Change | Where | Check |
|---|---|---|
| Typing suggestions (accessible combobox: arrows, Enter sends, Tab fills, Esc closes) | `web/index.html`; index from `bolosip/suggest.py` via `/api/config` (5 KB, matched in the browser, no request per keystroke) | `tests/test_suggest.py`: all 324 scheme suggestions give that scheme's fact on BM25 and on embeddings; general questions are offered only if the search in use answers them. `tests/test_ui_browser.py` drives it with the keyboard |
| "Ask next" / "Try instead" chips, capability note after two misses | `web/index.html` | `tests/test_ui_browser.py` |
| Stamp-duty synonyms | `bolosip/topics.py` | Paraphrases 96.3% → 97.5%; held-out still 50/50 |
| Follow-up only with a signal | `bolosip/pipeline.py` | CONV-28; all 68 conversation turns pass |
| Usage report | `scripts/usage_report.py` | `tests/test_usage_report.py` (counts; no question text by default; no personal data) |
| Browser tests (`webapp-testing` skill approach) | `tests/test_ui_browser.py`, CI job `ui` | Runs headless Chromium in CI; skipped on a laptop without Playwright |

## 4. Not changed, on purpose

- **Lowering the confidence bar** to catch "where do I download my transaction history" (0.66) would let out-of-scope questions through (highest out-of-scope score 0.695). Kept as ISS-016 for Phase 8 tuning.
- **Speed:** already p50 25–32 ms, p95 ≤ 46 ms per message on a laptop; suggestions run in the browser with no network round trip.
