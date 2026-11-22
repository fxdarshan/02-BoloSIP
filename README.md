# BoloSIP

> **Facts-only. No investment advice.**

BoloSIP is a small retrieval-based FAQ assistant that answers factual questions about 27 HDFC Mutual Fund schemes: expense ratio, exit load, minimum SIP, riskometer, benchmark, and how to download statements. Every answer is at most 3 sentences, cites exactly one source, and shows when that source was last updated. It refuses advice and opinion questions, and never asks for or stores personal details.

**Status:** under construction. Phases 0 (foundation), 1 (data for all 27 schemes), 2 (personal-data, advice and returns checks), 3 (scheme resolution and retrieval), 4 (answers in the terminal), 5 (threads and the JSON API) and 6 (the chat page) are done; see the [implementation plan](Doc/Implementation-plan.md).

Refresh the scheme data (fetches only the 27 Groww scheme pages; falls back to saved copies if offline):

```bash
python ingest.py
```

## Quick start

Requires Python 3.10 or newer. The core uses only the standard library.

Run the tests:

```bash
python -m unittest discover tests
```

Run the evaluation report for a phase:

```bash
python -m eval.run --phase 0
```

Run every check (tests + evaluation gates) in one go:

```bash
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

On macOS / Linux use `sh scripts/check.sh`. The same checks run on GitHub after every push (Python 3.10–3.13, Windows and Linux).

## Better retrieval: local embeddings + ChromaDB (recommended)

BoloSIP finds the right fact for about 93% of real-user questions with local embeddings, against 69% with its built-in keyword search ([retrieval research](Doc/retrieval-research.md)). The embedding packages (fastembed, ChromaDB) don't support Python 3.15 yet, so use a Python 3.12 environment. [`uv`](https://docs.astral.sh/uv/) creates one without touching your system Python:

```bash
uv venv --python 3.12 .venv
```

```bash
uv pip install --python .venv/Scripts/python.exe -e ".[embed]"
```

On macOS / Linux the interpreter is `.venv/bin/python`. Then build the vectors and the local ChromaDB collection. The first run downloads the embedding model (about 550 MB, once) into `.cache/models/`:

```bash
.venv/Scripts/python.exe ingest.py --embed-only
```

Everything stays on your computer: the model runs locally, ChromaDB is a local folder (`data/chroma/`), and its usage telemetry is switched off. Without this step BoloSIP still works, using keyword search.

To look at what is stored in ChromaDB, use the read-only viewer. It shows the collection summary, then each chunk's metadata, its text, the exact text that was embedded, and its vector:

```bash
.venv/Scripts/python.exe scripts/show_embeddings.py
```

Options: `--scheme hdfc-mid-cap` (or `official`), `--topic exit_load`, `--id hdfc-mid-cap:exit_load --full` (all 768 values), `--query "exit load of HDFC Mid Cap"` (the 5 nearest chunks with cosine scores), `--limit 0` (all records) and `--csv data/embeddings_view.csv` (every record and dimension, for a spreadsheet).

## Ask from the terminal

```bash
python -m bolosip "What is the expense ratio of HDFC Mid Cap Fund?"
```

Several questions on one line share a conversation, so follow-ups work:

```bash
python -m bolosip "HDFC Mid Cap exit load" "what about its benchmark?"
```

Run `python -m bolosip` with no question for an interactive prompt, or add `--json` to see the reply object. Use the Python 3.12 environment (`.venv/Scripts/python.exe -m bolosip …`) for the more accurate embedding search.

## Run the server

```bash
python server.py
```

Open http://127.0.0.1:8000 for the chat page: dark theme by default (sun/moon button for light), a list of chats on the left (a drawer on phones), and three example questions to start. Start typing a scheme or a topic ("mid cap exit", "ter", "statement") for suggested questions; after each answer, chips offer the next questions. The JSON API is under `/api/`.

To see how people use it (reply mix, "not found" rate, answers per topic), run:

```bash
python scripts/usage_report.py
```

Add `--show-unanswered` to list the (redacted) questions that got "not found".

`GET /api/health` reports the 27 schemes and which search is in use. Conversations are kept in `data/bolosip.sqlite3` (git-ignored); personal details are replaced with `[redacted]` before anything is saved. Start the server with the Python 3.12 environment (`.venv/Scripts/python.exe server.py`) to use the embedding search.

## Daily data refresh (GitHub Actions)

Every day at **10:00 IST**, the `refresh-data` workflow on GitHub rebuilds BoloSIP's data from the 27 Groww pages: it scrapes them, parses and cleans the facts, chunks them, embeds the chunks and rebuilds ChromaDB, then runs every test and evaluation gate. Only if all of that passes does it commit the new data to `main` (as `github-actions[bot]`), and the run's summary page shows a change report. A failed or suspicious run (a missing scheme, or more than 5 stable facts changing at once) commits nothing and opens a GitHub issue labelled `data-refresh`.

Because the workflow commits every morning, **start local work with**:

```bash
git pull --rebase
```

Then restart the server to load the new data; it rebuilds its local ChromaDB collection from the new vectors by itself. `GET /api/health` shows `corpus_built_on` and `data_age_days`, and the server warns at start-up when the data is more than 3 days old. Never edit files under `data/` by hand; regenerate them with `python ingest.py`.

To run the refresh by hand (for example to try it without committing):

```bash
gh workflow run refresh-data.yml -f dry_run=true
```

To test the failure path (never commits): `-f force_failure=gate` fails the evaluation step, and `-f force_failure=blocked` makes the change report see six stable-fact changes. Either opens the `data-refresh` issue; the next normal run closes it.

To see what changed between two corpus versions:

```bash
python scripts/data_diff.py old_corpus.json data/corpus.json
```

## Browser tests (optional)

`tests/test_ui_browser.py` drives the chat page in headless Chromium with Playwright: examples, suggestions with the keyboard, chips, fallback, script text, the phone drawer, and an overflow scan at four widths. Without Playwright these tests are skipped; CI always runs them. To run them locally (Chromium is about 150 MB, downloaded once):

```bash
uv pip install --python .venv/Scripts/python.exe -e ".[ui-tests]"
```

```bash
.venv/Scripts/python.exe -m playwright install chromium
```

```bash
.venv/Scripts/python.exe -m unittest tests.test_ui_browser -v
```

## Settings and the Groq API key

All local settings live in a `.env` file in the project folder. It is git-ignored, so your key never reaches GitHub.

1. Copy the template (skip if `.env` already exists):

   ```bash
   copy .env.example .env
   ```

   On macOS / Linux use `cp .env.example .env`.

2. Open `.env` and paste your key after `GROQ_API_KEY=`. Get a key at [console.groq.com/keys](https://console.groq.com/keys).

   ```
   GROQ_API_KEY=gsk_your_key_here
   ```

3. Install the Groq SDK (only needed for LLM rephrasing):

   ```bash
   pip install groq
   ```

The Groq key is optional. Without it, BoloSIP answers with the source text directly. A variable set in your real environment overrides the same name in `.env`. See [.env.example](.env.example) for every setting.

## Documents

| Document | What it covers |
|---|---|
| [Problem statement](Doc/problem_statement.md) | Scope, the 27 schemes, response rules, acceptance criteria |
| [Architecture](Doc/architecture.md) | Components, data model, pipeline, API, security |
| [Implementation plan](Doc/Implementation-plan.md) | Phases 0–10 with tasks and exit criteria (Phase 7: daily data refresh at 10:00 IST) |
| [Edge cases](Doc/edge-case.md) | 234 corner cases and expected behaviour |
| [Evaluation](Doc/eval.md) | Datasets, metrics and pass thresholds per phase |
| [Retrieval research](Doc/retrieval-research.md) | Chunking, embedding model and vector store chosen by measurement for Phase 3 |
