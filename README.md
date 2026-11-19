# BoloSIP

> **Facts-only. No investment advice.**

BoloSIP is a small retrieval-based FAQ assistant that answers factual questions about 27 HDFC Mutual Fund schemes: expense ratio, exit load, minimum SIP, riskometer, benchmark, and how to download statements. Every answer is at most 3 sentences, cites exactly one source, and shows when that source was last updated. It refuses advice and opinion questions, and never asks for or stores personal details.

**Status:** under construction. Phases 0 (foundation), 1 (data for all 27 schemes), 2 (personal-data, advice and returns checks) and 3 (scheme resolution and retrieval) are done; see the [implementation plan](Doc/Implementation-plan.md).

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
| [Implementation plan](Doc/Implementation-plan.md) | Phases 0–9 with tasks and exit criteria |
| [Edge cases](Doc/edge-case.md) | 234 corner cases and expected behaviour |
| [Evaluation](Doc/eval.md) | Datasets, metrics and pass thresholds per phase |
| [Retrieval research](Doc/retrieval-research.md) | Chunking, embedding model and vector store chosen by measurement for Phase 3 |
