# Changelog

All notable changes to BoloSIP. Newest first.

## [Unreleased]

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
