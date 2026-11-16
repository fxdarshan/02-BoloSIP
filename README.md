# BoloSIP

> **Facts-only. No investment advice.**

BoloSIP is a small retrieval-based FAQ assistant that answers factual questions about 27 HDFC Mutual Fund schemes: expense ratio, exit load, minimum SIP, riskometer, benchmark, and how to download statements. Every answer is at most 3 sentences, cites exactly one source, and shows when that source was last updated. It refuses advice and opinion questions, and never asks for or stores personal details.

**Status:** under construction. Phase 0 (foundation) is done; see the [implementation plan](Doc/Implementation-plan.md).

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

Optional LLM rephrasing uses [Groq](https://console.groq.com). Install the SDK and set `GROQ_API_KEY`:

```bash
pip install groq
```

## Documents

| Document | What it covers |
|---|---|
| [Problem statement](Doc/problem_statement.md) | Scope, the 27 schemes, response rules, acceptance criteria |
| [Architecture](Doc/architecture.md) | Components, data model, pipeline, API, security |
| [Implementation plan](Doc/Implementation-plan.md) | Phases 0–9 with tasks and exit criteria |
| [Edge cases](Doc/edge-case.md) | 232+ corner cases and expected behaviour |
| [Evaluation](Doc/eval.md) | Datasets, metrics and pass thresholds per phase |
