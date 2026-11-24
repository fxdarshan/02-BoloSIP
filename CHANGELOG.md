# Changelog

All notable changes to BoloSIP. Newest first.

## [Unreleased]

### Changed (Apple-style look, 24 Nov 2026)
- System San Francisco font (Segoe UI Variable on Windows) with tighter tracking; Apple system grays (true black in dark mode) and system colours; Apple blue as the accent, with accessible shades so every text colour still meets WCAG AA in both themes.
- Frosted, translucent header, input and suggestion list; soft shadows instead of borders; pill buttons with a light spring on press.
- Two-line headline with a blue-to-purple gradient; app-icon style example tiles; iMessage-style blue question bubbles; quieter labels and source links in blue.

### Changed (UI refresh, 24 Nov 2026)
- Chat page redesigned beyond the Google Stitch draft: deeper surfaces with a soft accent glow; a welcome screen that shows the live data date (from `/api/health`), clickable topic shortcuts that start a question and open the typing suggestions, compact example cards and a three-point trust line; lighter answer cards (small kind label, larger text, highlighted figures, source link with its domain and the date on one line); a quieter "New chat" button; a focus ring on the input; gentle entry animations (off with reduced motion). Contrast (WCAG AA, both themes), the overflow scan at four widths and all browser tests pass.

### Added (Phase 8: optional LLM rephrasing, 24 Nov 2026)
- `bolosip/llm.py`: Groq `openai/gpt-oss-120b` (temperature 0, reasoning effort low, 200 completion tokens, 15 s timeout, 1 retry), a system prompt that allows only rewording of the one source fact, and a thread-safe budget for the account limits (30 requests and 8,000 tokens a minute, 1,000 requests and 200,000 tokens a day); a 429 pauses calls for Retry-After. Over a limit, on any error, or with no SDK or key, the answer stays extractive.
- Output checks (`composer.rejection_reason`): numbers and dates must match the fact after normalising (GAP-06) and none may be dropped; the plan name, quoted riskometer levels and words like "blocked" must stay; no URLs; no advice, including advice phrased as a statement ("you should invest"), which the question guard did not catch (ISS-050).
- Only `answer` replies are sent; `/api/health` reports `llm_enabled`; `BOLOSIP_LLM=on` refuses to start without the LLM.
- `eval/datasets/llm_stress.jsonl` (38 cases), the Phase 8 gate in `eval/run.py`, `eval/llm_live.py` (live report), `tests/test_llm.py` (16).
- The container also listens on port 8000 (`BOLOSIP_ALSO_PORT`), so the Railway domain works whichever port it targets (ISS-048); the image includes the `llm` extra.

### Added (deployment stage D0: ready for Railway, 23 Nov 2026)
- Chats belong to one browser: an `HttpOnly; SameSite=Strict` owner cookie (`Secure` over HTTPS); threads store its SHA-256; another browser's chat is a 404 (ISS-046). Old local chats are kept for the local browser.
- Runs behind Railway's edge: `PORT`, `BOLOSIP_PUBLIC_HOSTS` (default `RAILWAY_PUBLIC_DOMAIN`), `https://` origins, Railway's healthcheck Host for `/api/health` only, `BOLOSIP_TRUST_PROXY` (visitor IP from `X-Real-IP`), HSTS (ISS-047).
- Clean stop on SIGTERM (requests in flight finish, up to 8 s); `BOLOSIP_RETENTION_DAYS` deletes old chats at start-up and daily.
- `Dockerfile`, `.dockerignore`, `scripts/docker-entrypoint.sh` (non-root), `scripts/smoke_remote.py` (18–20 checks), `docker` CI job, `tests/test_deploy.py` (15 tests), `Doc/deployment-plan.md`.

### Added (Phase 7: scheduled daily data refresh, 22 Nov 2026)
- `.github/workflows/refresh-data.yml`: every day at 10:00 IST (and on demand, with a dry-run option) scrape, parse, clean, chunk, embed and build ChromaDB; the independent truth parser, all tests and every gate run before anything is committed; commit as `github-actions[bot]` only when data changed; one `data-refresh` issue opened on failure and closed after the next fully live run.
- `scripts/data_diff.py`: change report (daily / minor expense ratio / stable / official) in the run summary; blocks the commit on a missing scheme or more than 5 stable-fact changes.
- Stable embeddings: daily values (NAV, fund size, "as on" dates) are masked in the embedded text with a fixed amount of the same shape, vectors are keyed to the embedded texts (`texts_sha256`, per-row `text_sha256`) and only changed rows are re-embedded. Retrieval unchanged (paraphrases 97.5%, held-out 50/50, out-of-scope answered 0); a word mask had cost 3.7 pp and was replaced.
- `force_failure` input (`gate` / `blocked`) on the refresh workflow to test the failure path without committing; verified on 22 Nov 2026 (issue opened, updated, then closed by the next good run).
- `/api/health` adds `data_age_days`; the server warns at start-up when the data is more than 3 days old.
- Fixed a race in the typing suggestions (a pending close-on-blur could hide the list just after it opened), found by the browser tests in the full suite (ISS-043).
- Tests: `tests/test_data_diff.py` (8), daily-values test in `test_retrieval.py`, data-age test in `test_api.py`.

### Planned (22 Nov 2026)
- New **Phase 7: scheduled daily data refresh** (GitHub Actions at 10:00 IST: scrape, parse, clean, chunk, embed, ChromaDB, tests and gates, commit only if all pass; change report, blocking rules, `data-refresh` issue on failure; stable embeddings so daily NAV changes don't rewrite the vectors). Former Phases 7–9 (LLM rephrasing, acceptance, release) are now 8–10 across all docs and code comments. Problem statement v2.3 (§8), architecture v1.5 (§15.1), plan v1.5, eval v1.2.

### Improved (after Phase 6, 22 Nov 2026), from the chatbot-flow-design audit
- Typing suggestions in the input (accessible combobox), matched in the browser from a 5 KB index in `/api/config` (`bolosip/suggest.py`); only questions tested to get a correct answer are offered.
- "Ask next" chips after an answer; "Try instead" chips after not found, refusal and returns replies; a capability note after two misses in a row.
- Follow-ups only with a signal (ISS-039: on BM25, "bitcoin price" in a Mid Cap thread was answered with the NAV); stamp-duty synonyms (paraphrases 96.3% → 97.5%).
- `scripts/usage_report.py`: reply mix, fallback rate, answers per topic and scheme, repeated misses; question text only with `--show-unanswered`.
- `tests/test_ui_browser.py` (Playwright, the `webapp-testing` approach) and a CI `ui` job; `tests/test_suggest.py`, `tests/test_usage_report.py`; CONV-28.
- `Doc/issues.md` (every issue, open and fixed) and `Doc/design/chatbot-audit.md`.

### Added (Phase 6: web UI, milestone M2, 20 Nov 2026)
- `web/index.html`: one self-contained page (inline CSS, inline SVG icons, no external scripts or fonts): sticky header with the disclaimer, chat list (drawer below 700 px), welcome with 3 example cards, one card per reply kind with a big icon, highlighted values, source link and footer, clarify and help buttons, typing indicator, toasts for rate limits and network errors, 500-character input with counter, dark and light themes.
- Design: Google Stitch export reviewed in `Doc/design/ui-review.md` (screens and design notes in `Doc/design/stitch/`). Fixed the thick light borders and missing replies on mobile, the overflowing header and the broken logo; removed claims the project can't back (SEBI-compliant, AMFI live feed, verified snapshot) and every external dependency.
- `tests/test_web.py` (12): self-contained page, no `innerHTML`, safe links, optional storage, disclaimer, WCAG AA contrast in both themes, 1px borders only, security headers. `eval/manual/phase6_ui_check.json` (15 browser checks, incl. an overflow scan at 6 widths); Phase 6 gate. 225 tests.

### Added (Phase 5: thread store and HTTP API, 19 Nov 2026)
- `bolosip/store.py`: SQLite threads and messages (WAL, `synchronous=NORMAL`, foreign keys, busy timeout); one transaction per exchange; redacts again before storing; titles from the redacted first question; schema re-created if the file is deleted.
- `server.py`: standard-library JSON API (health, config, threads, messages, delete); Host and Origin checks, JSON-only POST, no CORS (GAP-08); per-IP token-bucket rate limits with `Retry-After` (GAP-09); 4 KB body, 500-character, UUID and method checks; 10 s socket timeout; security headers; logs without message text or error details; warning when bound to a public address.
- `eval/api_harness.py` (real server on a free port), `eval/pii_scan.py`; Phase 5 gate (API parity, context and isolation over HTTP, concurrency, personal-data scan, persistence, request safety, latency).
- Tests: `test_threads.py` (15), `test_api.py` (21); 213 tests.
- Fixed after CI: listen backlog raised from 5 to 128 (connection resets under 20 parallel requests); latency target enforced locally, reported on CI.
- Retriever: query embeddings are cached (one question can need three searches).
- Groq default model is now `openai/gpt-oss-120b`; the account's rate limits are in `config.GROQ_LIMITS` for Phase 8.

### Added (Phase 4: answer pipeline, milestone M1, 19 Nov 2026)
- `bolosip/formatter.py`: `Reply` (+ `to_dict`, `render`), URL stripping, 3-sentence limit, footer, `validate()`.
- `bolosip/composer.py`: extractive answers with a Phase 8 `rephrase` hook; fixed replies for refusal (AMFI), performance (factsheet, no figures), privacy (SEBI), clarify (≤ 5 candidates), help (3 examples), not found (closest official page), other fund house, non-fund HDFC, HDFC scheme not covered, Direct-Growth-only (GAP-05).
- `bolosip/pipeline.py`: `handle(text, ctx) -> (Reply, ctx)`, rules 1–6 in order; follow-ups, definitions, scheme-only questions, plan variants, ELSS, two-topic questions.
- `python -m bolosip`: ask from the terminal (several questions share a thread; `--json`; interactive mode).
- Sets: `help.jsonl`, `variants.jsonl`, `conversations.jsonl`; `eval/answer_eval.py`; Phase 4 gate (confusion matrix, samples per kind, 30 answers for human review).
- Tests: `test_format.py`, `test_pipeline.py`; 177 tests.
- Results (dense): core facts 135/135, all facts 324/324, format and citations 901/901, reply kind 99.8%, refusals 78/78, performance 36/36 with 0 figures, help 18/18, variants 12/12, ELSS 10/10, context 63/63.

### Added (19 Nov 2026)
- `scripts/show_embeddings.py`: read-only viewer for the ChromaDB collection (summary, per-chunk metadata, text, embedded text and vector; filters, nearest-chunk query, CSV export).

### Added (Phase 3: scheme resolution and retrieval, 19 Nov 2026)
- `bolosip/schemes.py`: `resolve()` returns one / ambiguous / multiple / other_amc / non_fund / not_covered / none; longest alias first; weak aliases (Sensex, silver, gilt, liquid…) need a fund signal; thread follow-ups only for scheme topics.
- `bolosip/embedder.py` (nomic-embed-text-v1.5 via fastembed, prefixes, L2-normalised, local cache only), `bolosip/vectorstore.py` (local ChromaDB `bolosip_facts`, cosine, scheme filter, telemetry off, rebuilt from the committed `data/embeddings.npy` + `.json` when missing or stale), `bolosip/retriever.py` (dense search with BM25 fallback; `BOLOSIP_RETRIEVER` = auto / embed / bm25; two-level thresholds; topic boost for ordering only).
- `ingest.py` builds embeddings after the corpus (`--embed-only`, `--no-embed`); ingestion never fails when the `embed` extra is missing.
- Question sets: `paraphrases.jsonl` (81), `ambiguous.jsonl` (40), `out_of_corpus.jsonl` (48), `holdout.jsonl` (60); `eval/retrieval_eval.py`; Phase 3 gate with per-topic and per-scheme accuracy and the top 5 for every miss.
- Tests: `test_schemes.py`, `test_retrieval.py` (BM25, stub dense path, backend selection, real-model tests); 141 tests.
- CI: new `embed` job (Python 3.12, `.[embed]`, cached model, vectors-up-to-date check, dense gate).
- Fixed: three advice false refusals; scheme lock-in keywords no longer outrank the ELSS note.
- Results (dense): facts 100%, general 95.7%, paraphrases 96.3%, held-out 100%, MRR@5 0.999, out-of-scope answered 0/58, wrong scheme 0. BM25: facts 100%, out-of-scope answered 0/58.

### Research: retrieval for Phase 3 (18 Nov 2026)
- `Doc/retrieval-research.md`: corpus profile and a benchmark of BM25, 5 embedding models, 3 chunk-text variants and hybrid fusion on 324 template, 23 general and 72 user-wording questions plus 14 out-of-scope questions.
- Decision: keep fact-level chunks; embed `search_document: {text} {keywords}` with local `nomic-embed-text-v1.5` (fastembed, ONNX): 93% vs 69% (BM25) on user wording, 100% out-of-scope rejection; no vector database (1 MB numpy matrix, exact search); BM25 fallback; hybrid rejected.
- Architecture v1.3 (§8 rewritten, P5, D3, config, limitations) and plan v1.3 (Phase 3 rewritten: embedder, embeddings file, held-out set, CI job on Python 3.12).
- Reproducible scripts and raw results in `eval/research/`.

### Audit of Phases 0–2 (18 Nov 2026)
Every task, test bullet and exit criterion of Phases 0–2 in the plan, and every Phase 0–2 gate in `eval.md`, re-checked against the code. Gaps fixed:
- `ingest.validate_corpus` now also re-checks the finished corpus for riskometer level (SEBI's 6), expense ratio (0–3%) and minimum SIP (≥ ₹1), not only while parsing; 3 tests added.
- Phase 1 gate: the per-scheme table (27 rows) required by `eval.md` is now in the report; fetch resilience now checks exit code 1 and that footer dates equal the recorded fetch dates; judgement scan now includes "low" outside SEBI levels and AMFI's factual "lower expense ratio".
- `eval/datasets/general.jsonl` (23 process and definition questions) created, as the Phase 2 false-refusal check requires; Phase 2 report now always lists every miss and false positive by ID.
- Cases added: PRF-09 (capital gains statement is not a returns question), "how much did it grow", "98765 43210"; test documenting the PII-29 limit (a PAN split across messages is not joined).
- `.env.example` documents `BOLOSIP_SKIP_DOTENV`; stale "MF Central" references removed (capital gains now cites HDFC's Request Statement page).

### Added (Phase 2: guards, 16 Nov 2026)
- `bolosip/guards.py` rewritten: ordered `check()` (personal data → advice → returns); personal data now covers PAN (plain or spaced), Aadhaar (incl. masked, partial with keyword, 16-digit VID), email (incl. "at … dot"), mobile (any grouping) and landline, OTP / verification codes, IFSC (GAP-07), account and folio numbers; ISINs and toll-free numbers are never flagged; redaction keeps the sentence readable.
- Advice check widened (opinions on costs, suitability, safety, loss, predictions, ratings, "top/highest returning", "would you invest", "overvalued") while letting factual questions through ("best way to download", "HDFC Top 100", "Multi Asset Allocation").
- Returns check: CAGR / XIRR / yield / NAV history / 52-week / calculators / "how did it do"; excludes capital-gains statements, "Total Return Index", tax returns and returning units.
- Question sets: `eval/datasets/advice.jsonl` (108), `performance.jsonl` (49), `pii.jsonl` (61), each with look-alike negatives; `tests/test_guards.py` (18 tests incl. per-pattern speed); 80 tests total.
- Phase 2 evaluation gate with confusion matrix.

### Added (Phase 1: corpus for 27 schemes, 16 Nov 2026)
- `bolosip/registry.py`: the 27 schemes with IDs, Groww URLs (the only URLs ingestion may fetch), ISINs, groups and aliases (shared aliases mark ambiguity).
- `bolosip/topics.py`, `bolosip/textutil.py`: shared topic lexicon; sentence splitter; return-figure and judgement-word patterns.
- `ingest.py` rewritten: URL allow-list, identity check (slug + ISIN), riskometer from the scheme's own data cross-checked with the page summary (GAP-03), templates for Nil / graded / 15%-rule exit loads, blocked lump-sum, Groww placeholder benchmark; full validation; atomic write and lock (GAP-04); `--offline`; exit codes 0/1/2.
- `data/corpus.json`: 334 chunks (27 × 12 + 10 official notes), all 27 pages fetched live; `data/raw/` 27 snapshots + `fetched.json`.
- `data/official_docs.json`: every note re-checked against its source; 7 re-pointed to the page that states the fact.
- Tests: `tests/test_ingest.py` (40 tests) with frozen fixtures; 61 tests in total.
- Evaluation: `eval/build_truth.py` (independent parser) → `eval/datasets/facts.jsonl` (324 cases); Phase 1 gate in `eval/run.py`; live spot check record.

### Fixed
- CI evaluation gate failed on Python 3.10 / 3.11 because a start-up site hook (`_distutils_hack`) was blamed on BoloSIP.

### Added (Phase 0: foundation, 16 Nov 2026)
- `bolosip/config.py`: settings from `.env` and environment variables with safe defaults and clear errors; retrieval constants; request limits; Groq call settings; official links; other-AMC names; UI text.
- `.env.example` settings template; local `.env` (git-ignored) holds `GROQ_API_KEY`.
- Tests: `tests/test_smoke.py`, `tests/test_env_file.py` (21 tests, standard library only).
- Evaluation runner `eval/run.py` with the Phase 0 gate; first gate report in `eval/reports/`.
- Project files: `pyproject.toml`, `requirements.txt`, `.gitattributes`, `.editorconfig`, CI workflow (Python 3.10–3.13 on Windows and Linux), `scripts/check.ps1` / `check.sh`, `scripts/md_to_txt.py`.

### Changed
- Optional LLM provider is **Groq** (`groq` SDK, default model `llama-3.3-70b-versatile`) instead of Claude, across all docs.

### Documentation
- Problem statement v2.2: 27 HDFC schemes, source policy, response rules, acceptance criteria.
- Architecture v1.2, implementation plan v1.2, edge cases v1.2 (234 cases, 9 design gaps fixed), evaluation plan v1.1.

### Earlier work (before Phase 0)
- `ingest.py`: fetches scheme pages (urllib → curl → snapshot fallback) and builds `data/corpus.json`. Currently 5 of 27 schemes; extended in Phase 1.
- `bolosip/guards.py`: draft personal-data, advice and returns checks; tested in Phase 2.
- `data/official_docs.json`: hand-curated notes from HDFC MF, AMFI, SEBI, CAMS and MF Central.
