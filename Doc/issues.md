# BoloSIP: issues log

> **Facts-only. No investment advice.**

Every error and issue found while building BoloSIP: what happened, why, how it was fixed, and where. Newest first within each section. Open issues are at the top. Keep this file updated whenever a new issue is found or closed.

**Status:** 🔴 open · 🟡 open, accepted or waiting on a person · 🟢 fixed

---

## Open

| ID | Status | Found | Area | Issue | Notes / next step |
|---|---|---|---|---|---|
| ISS-038 | 🟡 | 22 Nov 2026 | Guards | "what tax do I pay when I buy HDFC Gilt Fund units" is refused as advice; the stamp-duty fact (or `not_found`) would be better | Safe failure (no wrong fact). Revisit with the Phase 8 paraphrase set |
| ISS-033 | 🔴 | 22 Nov 2026 | CI | One unit test failed once on the Windows / Python 3.13 job only (passed in every other job and in the same job minutes earlier); the gate did not say which test | Gate now names failing tests (`eval/run.py` phase 0). Identify and fix if it recurs |
| ISS-024 | 🔴 | 19 Nov 2026 | Data | `data/embeddings.json` was found with one chunk ID mangled (`hdfc-balanced-advantage:category` → `hdfcalanced-advantage:category`), breaking the Chroma rebuild. Nothing in the code writes that file outside ingestion | Restored from git; not seen again. Root cause unknown; the CI "committed vectors are up to date" check would catch a repeat |
| ISS-020 | 🟡 | 19 Nov 2026 | Process | Human checks still to do: M1 review of 30 answers (Phase 4 gate report), Edge pass, Lighthouse score ≥ 90, screen-reader pass, 3-person usability check (Phase 6) | Owner |
| ISS-016 | 🟡 | 19 Nov 2026 | Retrieval | Three near-threshold misses on the dense path with no scheme named: "Where can I download the monthly factsheet?" (0.70), "where do I download my transaction history" (0.66), "what is ELSS" (0.70, answered correctly by the pipeline's ELSS rule) | Lowering the 0.70 bar would let out-of-scope questions through (highest out-of-scope score 0.695). Re-tune in Phase 8 |
| ISS-015 | 🟡 | 19 Nov 2026 | Retrieval | BM25 fallback (Python 3.15, no embeddings): definition questions inside a thread ("what is a riskometer?") return `not_found`, because BM25's no-scheme bar is high | Marked `dense_only` in `conversations.jsonl`; dense is the default |
| ISS-010 | 🟡 | 19 Nov 2026 | Evaluation | The held-out set was run once before the weak-alias and topic-boost changes, and one of its misses motivated the weak aliases, so its 100% is slightly optimistic | Write fresh held-out cases in Phase 8 |
| ISS-009 | 🟡 | 19 Nov 2026 | Retrieval | Thin margin between the no-scheme bar (0.70) and the highest out-of-scope score (0.695) | The resolver checks (other fund house, non-fund HDFC, schemes not covered, weak aliases) are the first defence. Re-tune in Phase 8 |

---

## Fixed

### Phase 6+ improvements (22 Nov 2026)

| ID | Issue | Cause | Fix |
|---|---|---|---|
| ISS-037 | Playwright wasn't installed on the laptop, so the browser tests only ran in CI | Optional tool, not part of the core setup | Installed in `.venv` (Playwright 1.65.2 + headless Chromium, 22 Nov 2026); all 7 browser tests pass locally. Documented as the `ui-tests` extra in `pyproject.toml` and in the README |
| ISS-042 | CI: the first run of the Playwright browser tests failed in 5 of 7 tests | `page.wait_for_function` evaluates a string, which the page's Content-Security-Policy (no `unsafe-eval`) blocks: the policy working as intended | Tests poll with `page.evaluate()` and locator waits instead |
| ISS-041 | At 320 px with a wide system font (DejaVu Sans on Linux, some Android fonts) the page scrolled sideways (337 px) | The disclaimer pill was set to never wrap, so one line was wider than the screen and pushed the header and page | The disclaimer may wrap on narrow screens; the browser test now also scans with a wide font. Found by the new CI `ui` job |
| ISS-040 | Typing suggestions ranked badly while being built: a duplicate entry; "small cap" offered Large Cap's minimum SIP; "ter" offered Ultra Short **Ter**m first; "who man" offered expense ratio ("management fee") | Prefix matching treated all matches alike | Whole-word matches beat prefixes; scheme-name matches beat topic synonyms; template words add a bonus; duplicates removed |
| ISS-039 | BM25 fallback: "bitcoin price" asked in a Mid Cap thread was answered with Mid Cap's NAV (a wrong fact); "and bitcoin price?" likewise | An unrecognised question borrowed the thread's scheme; the scheme-filtered keyword search matched "price" under the lenient scheme bar | `pipeline.py`: the thread's scheme only with a follow-up signal (pronoun, named topic, "and/also/what about", plan word); a scheme taken from the thread with no named topic must clear the no-scheme bar. Regression case CONV-28. Found by `tests/test_usage_report.py` |
| ISS-036 | Reply to "is any government duty charged when I invest in HDFC Liquid Fund" ended with "You can ask separately about the category and objective" | "invest in" is a category phrase; the two-topic note counted it as a second question | `pipeline.py`: the category topic never triggers the two-topic note |
| ISS-035 | "is any government duty charged when I invest in HDFC Liquid Fund" answered with the category fact | The stamp-duty topic only knew the words "stamp duty" | `topics.py`: stamp-duty synonyms ("government duty", "duty charged", "duty on purchase"); corpus and vectors rebuilt. Paraphrases 96.3% → 97.5% |
| ISS-034 | Running the downloaded `skill-scanner` script was blocked by Claude Code's permission system | Auto-mode classifier treats running freshly downloaded code as risky | Did the same checks by hand (search for hidden characters, injection phrases, hooks, load-time commands, URLs) |

### Phase 6: web UI (20–22 Nov 2026)

| ID | Issue | Cause | Fix |
|---|---|---|---|
| ISS-032 | Dark theme "faint" text (timestamps, counter) only 4.0:1 contrast on raised cards | Colour `#7f8a85` below WCAG AA 4.5:1 | Raised to `#8d9893` (≥ 4.83:1); `tests/test_web.py` checks every text and icon colour in both themes |
| ISS-031 | Mobile drawer appeared shifted left after opening | Focusing a button while the drawer slid in made the browser scroll the page sideways | `focus({ preventScroll: true })` |
| ISS-030 | Delete icon landed inside the delete-confirmation box | Icon centred on the whole list item, which grew when the box opened | Icon anchored to the thread row |
| ISS-029 | Example-card text centred instead of left-aligned | Buttons centre text by default | `text-align: left` on the cards |
| ISS-028 | Google Stitch design: 2px light-grey borders on mobile looked like thick white lines; desktop and mobile looked like different products | Mobile used the light `outline` colour (#85948c) at 2px | One component set for every width; 1px hairline borders at ≤ 18% opacity; a test forbids thicker borders |
| ISS-027 | Stitch mobile conversation showed only user bubbles (no replies), header overflowed ("RESEARCH ENGINE" wrapped, rate-limit badge over its text), broken logo image | Generated layout | Rebuilt as `web/index.html`; overflow scan at 1440/1024/768/719/375/320 px finds 0 issues |
| ISS-026 | Stitch design made claims the project can't back ("SEBI-compliant", "AMFI live feed", "Verified snapshot v4.8", "Fact checked"), showed a user avatar, sample chats about other fund houses, and echoed a PAN in a chat bubble | Generated content | Removed; a test keeps the claims out; after a privacy reply the thread is redrawn from the stored, redacted text |
| ISS-025 | Stitch code loaded Tailwind CDN, Google Fonts and an icon font | Generated code | Inline CSS, system fonts, inline SVG icons; the server's Content-Security-Policy allows only same-origin |

### Phase 5: threads and API (19 Nov 2026)

| ID | Issue | Cause | Fix |
|---|---|---|---|
| ISS-023 | CI (Windows): latency unit test failed with p50 53.6 ms against 50 ms | Shared CI runners are slow and noisy | Unit test keeps a loose bound (p50 < 250 ms); the gate enforces the real target on local runs and only reports it on CI |
| ISS-022 | CI (Linux): connection resets with 20 parallel requests | `socketserver`'s default listen backlog is 5 | `request_queue_size = 128` |
| ISS-021 | Latency p95 spiked to 274 ms in some runs (p50 steady at 25 ms) | SQLite fsync on every commit in WAL mode with `synchronous=FULL`, slow on Windows | `PRAGMA synchronous = NORMAL` (crash-safe in WAL); warm-up before measuring |
| ISS-019 | PII scan flagged 4-digit fragments ('0123', '4567') as leaked | Short digit runs appear by chance in UUIDs, timestamps and SQLite pages | `eval/pii_scan.py`: user text (titles, user messages) checked for every value; raw bytes and logs only for values of 8+ characters |
| ISS-018 | Embed-mode unit tests failed on the "stale vectors" test | The test inherited `BOLOSIP_RETRIEVER=embed` from the environment | Tests pin `mode="auto"` |

### Phase 4: answer pipeline (19 Nov 2026)

| ID | Issue | Cause | Fix |
|---|---|---|---|
| ISS-017 | "how to close my HDFC savings account" and "current gold ETF price" got "which scheme?" | The fund-signal check saw "HDFC"/"ETF" | `pipeline.py`: not-a-scheme terms (gold, bank accounts, cards, loans, insurance, FDs, demat) → `not_found` |
| ISS-014 | Shell heredoc wrote backspace characters instead of `\b` into a regex in `pipeline.py` | Escape handling in the Windows Git Bash heredoc | Rewrote the line directly; a check for `\x08` in source files |
| ISS-013 | Terse follow-ups ("its aum", "what is its nav") returned `not_found` | Short questions score under the bar | When a scheme is known and the topic is named, and the search ranks that scheme's fact first among its facts, that fact is the answer |
| ISS-012 | Definition questions in a thread ("what is a riskometer?") answered with the thread's scheme fact | Topic words alone triggered the follow-up rule | Definition wording ("what is a/an", "meaning of", "what does … include") never uses the thread's scheme |
| ISS-011 | "what about its exit load?" answered with the general exit-load definition, not the scheme's fact | The definition note scored above the scheme fact | Scheme's own fact wins when the topic is named |

### Phase 3: retrieval (18–19 Nov 2026)

| ID | Issue | Cause | Fix |
|---|---|---|---|
| ISS-008 | CI embed job: real-model tests silently skipped and the dense gate failed | Vectors were up to date, so `--embed-only` never downloaded the model | `--embed-only` always caches the model; real-model tests never skip in embed mode |
| ISS-007 | BM25 ranked scheme lock-in facts above the ELSS note for "ELSS lock-in period" | Repeated "lock in" keywords and "elss tax saving" in scheme lock-in keywords | Keywords trimmed |
| ISS-006 | Chroma tests failed to clean up on Windows | Chroma keeps its index file open | `TemporaryDirectory(ignore_cleanup_errors=True)` and clearing Chroma's client cache |
| ISS-005 | "what does expense ratio include" regressed after adding the topic boost | Boost pushed scheme facts over the definition when no scheme was named | Boost only when a scheme is named, and only for ordering |
| ISS-004 | "what is the Sensex today" answered as the Sensex Index Fund (a held-out miss) | "sensex" alias matched an everyday market term | Weak aliases need a fund signal; out-of-corpus cases added |
| ISS-003 | HDFC schemes outside the 27 (e.g. "HDFC Gold ETF FoF") were matched to a covered scheme or answered | No "not covered" resolution | `not_covered` kind |
| ISS-002 | Three advice false refusals: "compared against", "sell units within a year", "lose money to exit charge" | Advice patterns too broad | Patterns narrowed; each added as a test case |
| ISS-001 | Cosine bar 0.74 rejected too many general questions | Single bar for all questions | Two-level thresholds (0.70 no scheme / 0.62 scheme named; BM25 15 / 3) |

Earlier setup problems (Phase 3 tooling): the research model cache copied as broken symlinks (fixed with `cp -rL`); `python -I` broke imports for `ingest.py`; `vectorstore` default arguments bound file paths at import time (now resolved at call time).
