# BoloSIP: Architecture

> **Facts-only. No investment advice.**

Version 1.2 · 16 Nov 2026 · Implements [problem_statement.md](problem_statement.md) v2.2 · v1.2: the optional LLM is **Groq** · v1.1 added the 9 design-gap fixes from [edge-case.md](edge-case.md) §16 (marked **GAP-xx** below)

---

## 1. Purpose and design principles

BoloSIP is a small Retrieval-Augmented Generation (RAG) assistant. It answers factual questions about 27 HDFC Mutual Fund schemes. Every answer has at most 3 sentences, exactly one source link, and a "Last updated from sources" date.

These principles drive the design. When two pull in different directions, the first one wins.

| # | Principle | What it means in the design |
|---|---|---|
| P1 | **Safety before helpfulness** | Personal-data, advice and returns checks run *before* retrieval, so a disallowed question never reaches the corpus or an LLM. |
| P2 | **Accuracy over intelligence** | The source text is the answer. An LLM may only rephrase it, and the system works fully without one. |
| P3 | **One fact, one source** | The corpus is split into single-fact chunks, each carrying its own source URL and date. The citation comes from the chunk, never from the model. |
| P4 | **Code enforces the rules** | Sentence limit, single link and footer are added or checked in code after composition, not left to a prompt. |
| P5 | **Small and inspectable** | Python standard library plus one optional dependency (`groq`). The corpus is one JSON file you can read, diff and review in git. |

## 2. System context

```mermaid
flowchart LR
    U([User in browser]) -->|HTTP JSON| S[BoloSIP server]
    S --> DB[(SQLite threads)]
    S --> C[(corpus.json)]
    S -.optional.-> L[Groq API]
    I[ingest.py] -->|writes| C
    I -->|fetches| G[27 Groww scheme pages]
    O[official_docs.json<br/>hand-curated: HDFC MF, AMFI,<br/>SEBI, CAMS, MF Central] --> I
```

| Actor / system | Role | Trust |
|---|---|---|
| User | Asks questions in one or more threads | Untrusted input |
| BoloSIP server | Guards, retrieval, answer composition, thread storage | Trusted |
| `corpus.json` | Read-only knowledge base, built offline | Trusted (reviewed in git) |
| Groww scheme pages | Source of scheme facts (the brief's named exception) | Fetched data; parsed, never executed |
| Official pages | Source of process and education notes | Curated by hand, with a review date |
| Groq API | Optional rephrasing of retrieved text (third-party service) | Output checked before use; receives no personal data |

## 3. Components

```mermaid
flowchart TB
    subgraph Offline["Offline: build the corpus"]
        F[Fetcher<br/>urllib → curl → snapshot] --> P[Parser<br/>embedded page JSON]
        P --> K[Chunker<br/>one fact per chunk]
        OD[official_docs.json] --> K
        K --> CJ[(data/corpus.json)]
    end

    subgraph Online["Online: answer a message"]
        API[HTTP API<br/>server.py] --> PIPE[Pipeline<br/>bolosip/pipeline.py]
        PIPE --> GU[Guards<br/>bolosip/guards.py]
        PIPE --> SR[Scheme resolver<br/>bolosip/schemes.py]
        PIPE --> RT[Retriever<br/>bolosip/retriever.py]
        PIPE --> CO[Composer<br/>bolosip/composer.py]
        CO -.optional.-> LLM[Groq client<br/>bolosip/llm.py]
        PIPE --> FM[Formatter + validator<br/>bolosip/formatter.py]
        API --> ST[Thread store<br/>bolosip/store.py]
        RT --> CJ
        SR --> CJ
    end

    UI[web/index.html] --> API
```

| Component | File | Responsibility | Status |
|---|---|---|---|
| Ingestion | `ingest.py` | Fetch scheme pages, parse them, build chunks, merge official notes, write `corpus.json` | Built for 5 schemes; extend to 27 |
| Guards | `bolosip/guards.py` | Detect personal data, advice questions and returns questions; redact | Draft, untested |
| Scheme resolver | `bolosip/schemes.py` | Map free text to a scheme ID using aliases; detect ambiguity; use the thread's last scheme | Planned |
| Retriever | `bolosip/retriever.py` | BM25 ranking plus topic and scheme boosts; returns a ranked list with scores | Planned |
| Composer | `bolosip/composer.py` | Turn the top chunk into answer text, extractive by default with LLM rephrasing optional | Planned |
| LLM client | `bolosip/llm.py` | Thin wrapper around the Groq SDK; returns `None` on any failure | Planned |
| Formatter | `bolosip/formatter.py` | Enforce ≤ 3 sentences, strip stray URLs, attach one citation and the footer | Planned |
| Pipeline | `bolosip/pipeline.py` | Run the ordered decision rules (section 6) and return a `Reply` | Planned |
| Thread store | `bolosip/store.py` | SQLite persistence of threads and redacted messages | Planned |
| HTTP server | `server.py` | Serve the UI and JSON API from the standard library's `ThreadingHTTPServer` | Planned |
| UI | `web/index.html` | Single page: welcome, 3 examples, disclaimer, thread list, chat | Planned |
| Tests | `tests/` | Acceptance tests from problem statement section 10 | Planned |

## 4. Directory layout

```
02 BoloSIP/
├── Doc/
│   ├── problem_statement.md / .txt      # spec (v2.1)
│   ├── problem_statement_original.txt   # original brief
│   └── architecture.md                  # this file
├── ingest.py                            # offline corpus builder
├── server.py                            # HTTP server + API
├── bolosip/
│   ├── __init__.py
│   ├── config.py                        # env vars, paths, thresholds
│   ├── guards.py
│   ├── schemes.py
│   ├── retriever.py
│   ├── composer.py
│   ├── llm.py
│   ├── formatter.py
│   ├── pipeline.py
│   └── store.py
├── data/
│   ├── official_docs.json               # hand-curated official notes (in git)
│   ├── corpus.json                      # generated, committed for review
│   ├── raw/<scheme-id>.html             # last good page snapshot per scheme
│   └── bolosip.sqlite3                  # runtime threads (git-ignored)
├── web/
│   └── index.html
├── tests/
│   ├── test_guards.py
│   ├── test_retrieval.py
│   ├── test_format.py
│   ├── test_threads.py
│   └── test_acceptance.py
├── requirements.txt                     # groq (optional)
└── README.md
```

## 5. Data model

### 5.1 Scheme registry

This is built by `ingest.py` and stored in `corpus.json` under `schemes`. It is the single source of truth for which schemes exist and what users may call them.

```json
"hdfc-flexi-cap": {
  "name": "HDFC Flexi Cap Fund Direct Growth",
  "url": "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
  "group": "Equity",
  "category": "Flexi Cap",
  "aliases": ["flexi cap", "flexicap", "hdfc equity fund", "hdfc equity"],
  "factsheet_url": "https://www.hdfcfund.com/mutual-funds/factsheets"
}
```

- **Scheme ID:** a stable slug of the *current* name, not the URL. So `hdfc-equity-fund-…` becomes `hdfc-flexi-cap`.
- **Aliases:** lowercase phrases used for matching. Former names (e.g. "hdfc equity fund") are included. An alias that fits more than one scheme is listed under each of them, and the resolver treats a match on it as ambiguous (section 7).

### 5.2 Chunk

Each chunk holds exactly one fact plus its provenance.

| Field | Type | Example | Notes |
|---|---|---|---|
| `id` | str | `hdfc-mid-cap:expense_ratio` | `<scheme-id>:<topic>` or `official:<name>` |
| `scheme_id` | str \| null | `hdfc-mid-cap` | `null` for general or official notes |
| `scheme_name` | str \| null | `HDFC Mid Cap Fund Direct Growth` | |
| `topic` | str | `expense_ratio` | See topic list below |
| `text` | str | "The expense ratio (TER) of … is 0.73% per annum, as on 12 Nov 2026." | ≤ 3 sentences, self-contained |
| `keywords` | str | "expense ratio ter cost charges …" | Synonyms that help matching |
| `source_url` | str | Groww or official URL | Becomes the citation |
| `source_name` | str | "HDFC Mid Cap Fund … scheme page" | Link label in the UI |
| `as_of` | str | `16 Nov 2026` | Fetch or review date; becomes the footer |

**Scheme topics (12 per scheme):** `expense_ratio`, `exit_load`, `min_investment`, `riskometer`, `benchmark`, `lock_in`, `fund_manager`, `category`, `nav`, `aum`, `scheme_details`, `stamp_duty`.

**Official topics:** `statement`, `capital_gains`, `lock_in_general` (ELSS), `riskometer_general`, `expense_ratio_general`, `exit_load_general`, `plans_general`, `sip_general`, `factsheet`.

**Expected size:** 27 × 12 + about 10 official notes, roughly 335 chunks (well under 1 MB). This is small enough to load fully into memory at start-up.

**Deliberately not chunked:** returns, peer comparisons, Groww's "pros/cons" analysis, ratings and category tax text. These are performance or opinion data, so they must never be retrievable.

### 5.3 Thread store (SQLite)

```sql
CREATE TABLE threads (
  id          TEXT PRIMARY KEY,          -- uuid4
  title       TEXT NOT NULL,             -- first question, redacted, ≤ 60 chars
  created_at  TEXT NOT NULL,             -- ISO-8601 UTC
  updated_at  TEXT NOT NULL,
  last_scheme TEXT                       -- scheme_id used for follow-ups
);

CREATE TABLE messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id   TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('user','assistant')),
  text        TEXT NOT NULL,             -- user text is ALWAYS redacted before insert
  kind        TEXT,                      -- answer | refusal | performance | privacy | clarify | help | not_found
  source_url  TEXT,
  source_name TEXT,
  as_of       TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_messages_thread ON messages(thread_id, id);
```

## 6. Request pipeline

Each message goes through a fixed sequence of checks. The first one that matches decides the reply, which matches decision rules 1–6 in the problem statement.

```mermaid
flowchart TD
    A[User message] --> B{1. Personal data?}
    B -- yes --> B1[privacy reply<br/>store redacted text only<br/>no LLM call]
    B -- no --> C{2. Advice / opinion?}
    C -- yes --> C1[refusal + AMFI/SEBI link]
    C -- no --> D{3. Returns / performance?}
    D -- yes --> D1[factsheet link only<br/>no figures]
    D -- no --> HP{Greeting / help /<br/>no meaningful words?}
    HP -- yes --> HP1[help reply<br/>welcome + 3 examples]
    HP -- no --> E[Resolve scheme<br/>other-AMC check → message → thread context]
    E --> F[Retrieve top chunks]
    F --> G{4. Needs a scheme but<br/>none or several match?}
    G -- yes --> G1[clarifying question<br/>lists candidate schemes]
    G -- no --> H{5. Score ≥ threshold?}
    H -- no --> H1[not in sources<br/>+ closest official link]
    H -- yes --> I[Compose answer<br/>extractive or LLM]
    I --> J[Format + validate<br/>≤3 sentences, 1 link, footer]
    J --> K[Reply]
```

### 6.1 Sequence for one request

```mermaid
sequenceDiagram
    participant UI as Browser
    participant API as server.py
    participant P as pipeline
    participant S as store
    participant R as retriever
    participant L as Groq LLM (optional)

    UI->>API: POST /api/threads/{id}/messages {text}
    API->>P: handle(text, thread_ctx)
    P->>P: guards (PII → advice → performance)
    P->>R: search(query, scheme_id)
    R-->>P: ranked chunks + scores
    alt LLM enabled and answer case
        P->>L: rephrase(question, top chunk text)
        L-->>P: text (or None on any error)
    end
    P->>P: format + validate (fall back to extractive if invalid)
    P-->>API: Reply
    API->>S: insert redacted user msg + reply, update last_scheme
    API-->>UI: 200 {reply}
```

### 6.2 The `Reply` object

The pipeline's single output type. The API serialises it directly to JSON.

```json
{
  "kind": "answer",
  "text": "The expense ratio (TER) of HDFC Mid Cap Fund Direct Growth is 0.73% per annum, as on 12 Nov 2026.",
  "source": {
    "url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    "name": "HDFC Mid Cap Fund Direct Growth scheme page"
  },
  "footer": "Last updated from sources: 16 Nov 2026",
  "scheme_id": "hdfc-mid-cap",
  "candidates": null
}
```

`kind` is one of `answer | refusal | performance | privacy | clarify | help | not_found`. Every kind except `clarify` and `help` carries exactly one `source` and a `footer`. The `clarify` kind carries `candidates`, a list of scheme names, and no link, because no fact is being stated.

**`help` kind (GAP-02).** Greetings ("hi", "thanks"), questions about BoloSIP itself ("what can you do?") and messages with no meaningful words after stop-word removal ("???", "what is the") get a short welcome plus the 3 example questions. Like `clarify`, it states no fact, so it has no link and no footer. It is detected after the three guards, so "hi, should I invest?" is still refused.

## 7. Scheme resolution

Users write "mid cap", "HDFC equity", "the sensex one", or "its exit load" as a follow-up. Resolution works in these steps:

0. **Other fund house check (GAP-01).** Before matching aliases, look for another AMC's name in the message, e.g. SBI, Axis, ICICI Prudential, Nippon, Kotak, Mirae, Parag Parikh / PPFAS, UTI, Aditya Birla Sun Life, DSP, Tata, Quant, Motilal Oswal, Franklin Templeton, Edelweiss, Canara Robeco, Bandhan, Invesco, HSBC, WhiteOak, Mahindra Manulife, Baroda BNP Paribas, Sundaram, LIC, Union, PGIM, 360 ONE, Navi, Bajaj Finserv, Helios, Samco, JM, ITI, Shriram, Quantum, NJ. If one is found and "HDFC" is not, reply `not_found`: "BoloSIP only covers HDFC Mutual Fund schemes." Without this, "SBI Small Cap exit load" would match the alias "small cap" and be answered with **HDFC** Small Cap data. The list lives in `config.py` and is matched on whole words after normalisation.
1. **Alias match on the message.** Lowercase the text, normalise `&`→`and` and hyphens→spaces, then find every alias that appears. Longest match wins, so "large and mid cap" beats "large cap" and "mid cap".
2. **Count distinct schemes matched:**
   - **one:** use it.
   - **several, because the user named several** (e.g. "mid cap and small cap"): if this is a comparison, guard 2 has already refused it. Otherwise ask the user to pick one, since an answer can cite only one source.
   - **several, because the phrase itself is ambiguous** (e.g. "hdfc equity" could be Flexi Cap or Equity Savings): clarify, listing the candidates.
   - **none:** go to step 3.
3. **Thread context.** If the topic is scheme-specific (e.g. `exit_load`) and the thread has a `last_scheme`, use it. If not, clarify.

General topics (`statement`, `capital_gains`, ELSS rules, definitions) never need a scheme.

**Plan and option variants (GAP-05).** The corpus holds only the **Direct plan, Growth option** of each scheme. If the message mentions "regular", "IDCW", "dividend" or "payout" together with a scheme-specific topic:

- for topics that differ between variants (`expense_ratio`, `nav`, `aum`, `scheme_details`), reply `not_found` saying only the Direct Growth plan is covered, with the scheme page link;
- for topics shared by all variants of the scheme (`exit_load`, `min_investment`, `riskometer`, `benchmark`, `lock_in`, `fund_manager`, `category`, `stamp_duty`), answer normally, and the formatter prefixes "For the Direct Growth plan: " so the plan is never left implicit.

**Known confusable groups** (each must have a test):

| Group | Schemes |
|---|---|
| Large-cap family | Large Cap · Large & Mid Cap · NIFTY 50 Index · BSE Sensex Index |
| "Equity" | Flexi Cap (formerly HDFC Equity) · Equity Savings |
| Cash-like debt | Overnight · Liquid · Money Market · Ultra Short Term |
| "Multi" | Multi Cap · Multi Asset Allocation |

## 8. Retrieval

### 8.1 Method

The corpus is small (about 335 chunks) and each chunk holds one short fact, so a lexical ranker works well. It is also deterministic and easy to debug, and needs no embedding model or vector database.

```
score(chunk) = BM25(query, chunk.text + chunk.keywords)
             + W_SCHEME  × [chunk.scheme_id == resolved scheme]
             + W_TOPIC   × [chunk.topic   == detected topic]
             − W_OTHER   × [chunk.scheme_id is another scheme]
```

- **Tokeniser:** lowercase, split on non-alphanumerics, drop a short stop-word list. Numbers are kept.
- **BM25 settings:** `k1 = 1.5`, `b = 0.75`, with the index built once at start-up.
- **Topic detection:** a keyword lexicon per topic (the same words used for `keywords` at ingest time) gives at most one detected topic.
- **Starting weights:** `W_SCHEME = 3.0`, `W_TOPIC = 3.0`, `W_OTHER = 5.0`. These are tuned on the acceptance test set and set in `config.py`.

### 8.2 Confidence threshold

The answer path is used only if the top score is at least `MIN_SCORE` **and** either the topic was detected or the top chunk's BM25 part alone clears `MIN_LEXICAL`. Otherwise the reply is `not_found`. Both thresholds are tuned so that every in-scope test question passes and every out-of-corpus test question (e.g. "expense ratio of SBI Bluechip") is refused.

### 8.3 Why not embeddings

| Option | Verdict |
|---|---|
| BM25 + boosts (chosen) | No dependencies, deterministic, explainable; handles a fixed vocabulary well |
| Sentence embeddings + vector DB | Adds a model download and a dependency; little gain on short, keyword-heavy questions |
| LLM-only (no retrieval) | Rejected: cannot guarantee citations or freshness, and risks hallucination |

The `Retriever` interface (`search(query, scheme_id, topic) -> list[Hit]`) is kept narrow, so an embedding retriever could be swapped in later without touching the pipeline.

## 9. Answer composition

### 9.1 Extractive mode (default, always available)

The answer text is the top chunk's `text`, unchanged. Chunks are written at ingest time to read as finished answers, so this is already correct and within the limits.

### 9.2 LLM mode (optional)

This mode uses **Groq** as the LLM provider. It is enabled when the `groq` package is installed, `GROQ_API_KEY` is set, and `BOLOSIP_LLM` is not `off`. The LLM is used **only to rephrase**, so the answer fits the user's wording. For example, "Is there any exit load?" can be answered "Yes, …" instead of just repeating the stored sentence.

| Setting | Value |
|---|---|
| Provider | Groq (fast hosted inference of open-weight models) |
| SDK | `groq` (official Python SDK): `from groq import Groq`, then `client.chat.completions.create(...)` |
| Client | `Groq(timeout=15.0, max_retries=1)`; reads `GROQ_API_KEY` from the environment |
| Model | `llama-3.3-70b-versatile` (a Groq production model; override with `BOLOSIP_MODEL`) |
| `temperature` | `0`: the same input gives the same rewording |
| `max_completion_tokens` | `200`: enough for 3 short sentences |
| Messages | `system` = rules below; `user` = question + **only the top chunk's text** (not the URL) |
| Timeout | 15 s, then extractive mode |

Groq retires and adds models over time, so the model ID lives only in `config.py` / `BOLOSIP_MODEL`. Check the current production list at console.groq.com/docs/models before each release. Smaller models (e.g. `llama-3.1-8b-instant`) are faster but must still pass the Phase 7 evaluation before being used.

**System prompt (outline):**

- Answer only from the provided source text, in at most 3 sentences.
- Do not add facts, numbers, opinions, advice, comparisons or URLs.
- If the source text does not answer the question, reply exactly `NOT_IN_SOURCE`.

**Output checks.** If any check fails, the system falls back to extractive mode:

- `choices[0].finish_reason` is `stop` (not `length`, which means the reply was cut off), and the text is not `NOT_IN_SOURCE`.
- Every number in the output also appears in the chunk text, so the model cannot invent figures. Numbers are **normalised before comparing (GAP-06)**: remove `₹`, `Rs`/`Rs.`, `INR` and thousands separators (both `1,00,687` and `100,687` become `100687`); drop trailing zeros after the decimal point (`0.730` → `0.73`); map the number words one to twelve to digits ("one year" = "1 year"); and accept `%` with or without a space. Dates are compared after parsing, so "12 Nov 2026" equals "12-Nov-2026".
- The output contains no URL and no advice words (it is run through `is_advisory`).

Messages flagged by guard 1 (personal data) are **never** sent to the LLM.

## 10. Formatting and validation

`formatter.py` is the last step for every reply except `clarify` and `help`.

1. Remove any URLs from the body text.
2. Split into sentences using `(?<=[.!?])\s+(?=[A-Z₹"])`. This does not split inside decimals such as "0.73%". Keep the first 3 sentences.
3. Attach `source` from the chunk (or from the guard's fixed link for refusal, performance and privacy replies).
4. Attach the footer `Last updated from sources: <as_of>`.
5. Check the result: 1–3 sentences, exactly one URL across body + source, footer present. If the check fails, return the extractive version. The tests also assert this check is never triggered by extractive text.

### 10.1 Fixed links per reply kind

| Kind | Link | Footer date |
|---|---|---|
| `answer` | Chunk `source_url` | Chunk `as_of` |
| `refusal` | AMFI investor page or SEBI investor site | `official_docs.reviewed_on` |
| `performance` | Scheme's `factsheet_url` (HDFC MF factsheets) | `official_docs.reviewed_on` |
| `privacy` | SEBI investor site | `official_docs.reviewed_on` |
| `not_found` | Closest official page (top general chunk, else AMFI) | That chunk's date |
| `clarify` | none | none |
| `help` | none | none |

## 11. Guards

`bolosip/guards.py` contains pure functions with no I/O, so they are easy to test exhaustively.

| Guard | Function | Approach | Main false-positive risks and mitigation |
|---|---|---|---|
| Personal data | `find_pii`, `redact` | Regex for PAN, Aadhaar, email, Indian mobile, OTP-with-digits, account/folio numbers, IFSC codes (`[A-Z]{4}0[A-Z0-9]{6}`, GAP-07), 9–18 digit runs | "account statement" must not match: account/folio rule requires a digit. AUM figures like "1,00,687" don't match because commas break digit runs. |
| Advice | `is_advisory` | Regex list: "should I", "which is better", "vs", "best", "recommend", "safe to invest", "will it grow", … | "best" in "BSE Sensex" doesn't match because of word boundaries. Comparison words ("vs", "compare") are refused on purpose, since comparisons are out of scope. |
| Performance | `is_performance` | "returns", "performance", "CAGR", "XIRR", "how much did", "calculate", "if I invest" … | "capital gains statement" is excluded explicitly because it's a document request. |

The guards run on the **raw** text. The redacted text is what gets stored and logged. Advice is checked before performance, so "Which fund gave better returns?" gets the advice refusal.

## 12. Multiple threads and concurrency

- **Isolation:** all conversation state is keyed by `thread_id`: message history and `last_scheme`. The pipeline gets the context for one thread only and keeps no global state between requests.
- **Server:** `http.server.ThreadingHTTPServer` handles each request on its own thread.
- **Read-only shared data:** the corpus and BM25 index are loaded once at start-up and never changed, so threads can read them safely without locks.
- **SQLite:** each request opens its own connection (`check_same_thread=False` is not needed). WAL mode is on (`PRAGMA journal_mode=WAL`) so reads don't block writes. A user message and its reply are written in one transaction.
- **LLM calls:** the Groq client is created once and shared between threads. Its HTTP client supports concurrent use.
- **Ordering:** the UI disables the send button for a thread while a request is in flight, so messages within one thread arrive in order. Different threads can still run at the same time.

## 13. HTTP API

All responses are JSON, and errors look like `{"error": "<message>"}`.

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/` | — | `web/index.html` |
| `GET` | `/api/health` | — | `{status, llm_enabled, corpus_built_on, schemes}` |
| `GET` | `/api/config` | — | `{welcome, examples[3], disclaimer}` for the UI |
| `GET` | `/api/threads` | — | `[{id, title, updated_at}]`, newest first |
| `POST` | `/api/threads` | — | `{id, title}` (new empty thread) |
| `GET` | `/api/threads/{id}/messages` | — | `[{role, text, kind, source, footer, created_at}]` |
| `POST` | `/api/threads/{id}/messages` | `{text}` (1–500 chars) | `Reply` (section 6.2) |
| `DELETE` | `/api/threads/{id}` | — | `204` |

**Input limits:** request body ≤ 4 KB, `text` ≤ 500 characters, and a thread ID must be a valid UUID. Everything else gets a `400`.

**Request origin checks (GAP-08).** The server listens on localhost, but any web page open in the user's browser can still send requests to it. Every request must pass:

- **`Host` header** is `127.0.0.1:<port>`, `localhost:<port>`, or the configured `BOLOSIP_HOST`; otherwise `403`. This blocks DNS-rebinding attacks.
- **`Origin` header**, when present, matches the server's own origin; otherwise `403` for `POST` and `DELETE`.
- **`POST` bodies** have `Content-Type: application/json`; otherwise `415`. A plain HTML form can't send that type without a CORS preflight, and the server sends no CORS headers, so the browser blocks it.

**Rate limiting (GAP-09).** An in-memory token bucket per client IP: by default 30 messages per minute and 120 requests per minute overall (`BOLOSIP_RATE_MSG`, `BOLOSIP_RATE_ALL`). Over the limit gets `429` with a `Retry-After` header. Counters reset on restart, which is enough for a single-node local app.

## 14. User interface

`web/index.html` is a single file with plain HTML, CSS and JavaScript: no build step, no framework, and no external scripts, fonts or trackers.

```
┌──────────────────────────────────────────────────────────────┐
│  BoloSIP   ⚠ Facts-only. No investment advice.     (sticky)  │
├───────────────┬──────────────────────────────────────────────┤
│ + New chat    │  Welcome! I answer factual questions about   │
│               │  27 HDFC Mutual Fund schemes…                │
│ ▸ Mid cap TER │                                              │
│   Exit loads  │  [What is the expense ratio of HDFC Mid Cap?]│
│   Statements  │  [What is the ELSS lock-in period?]          │
│               │  [How do I download my account statement?]   │
│               │                                              │
│               │  ┌ answer text (≤3 sentences)               │
│               │  │ Source: HDFC Mid Cap Fund… ↗             │
│               │  └ Last updated from sources: 16 Nov 2026    │
│               ├──────────────────────────────────────────────┤
│               │  [ Ask a factual question…        ] [Send]   │
│               │  Don't share PAN, Aadhaar, phone or OTP.     │
└───────────────┴──────────────────────────────────────────────┘
```

- **Disclaimer:** in a sticky header, so it is always visible.
- **Safe rendering:** all message text is inserted with `textContent`, never `innerHTML`. Source links get `rel="noopener noreferrer"` and `target="_blank"`.
- **Remembered thread:** the active thread ID is kept in `localStorage`, wrapped in try/catch. All other state lives on the server.
- **Narrow screens:** below 700 px the thread list becomes a drawer.

## 15. Ingestion pipeline

```mermaid
flowchart LR
    A[SCHEMES registry<br/>27 ids → url, aliases, group] --> B{fetch}
    B -->|urllib OK| D[parse embedded JSON]
    B -->|403 / TLS error| C[curl subprocess]
    C -->|OK| D
    C -->|fail| E[data/raw snapshot]
    E -->|exists| D
    E -->|missing| X[skip + report error]
    D --> F[save snapshot]
    F --> G[build 12 chunks]
    H[official_docs.json] --> I[merge]
    G --> I --> J[validate] --> T[write .tmp] --> K[(corpus.json<br/>atomic rename)]
```

- **Why fetching has fallbacks:** Groww returns `403` to Python's HTTP client but serves the page to `curl`. Python 3.13+ also rejects some certificate chains under `VERIFY_X509_STRICT`, so only that one flag is relaxed; certificates are still verified. If both live fetches fail, the last good snapshot is used, and its file date becomes `as_of`, so the footer stays honest.
- **Parsing:** read the page's embedded `__NEXT_DATA__` JSON (`props.pageProps.mfServerSideData`), not the visible HTML. It is structured and much more stable.
- **Identity check:** the parsed `search_id` and `isin` must match the registry entry, so a redirect to a different scheme is caught.
- **Riskometer (GAP-03):** don't search the raw page for the first `"risk":"…"`, because the peer-comparison funds on the same page carry the same field. Read the value from a fixed path inside the scheme's own JSON object, and cross-check it with the sentence in `meta_desc` ("… Risk is Very High"). If the two disagree, or the value isn't one of SEBI's 6 levels, validation fails for that scheme.
- **Atomic write (GAP-04):** write the new corpus to `corpus.json.tmp`, validate it, then replace `corpus.json` with an atomic rename (`os.replace`). An interrupted run can never leave a half-written file. A lock file (`data/.ingest.lock`) stops two runs at once.
- **Validation before writing.** If any check fails, the script exits non-zero and leaves the old `corpus.json` in place:
  - every scheme in the registry has all required topics, and every chunk has ≤ 3 sentences and a URL
  - expense ratio is between 0 and 3%, minimum SIP is a positive integer, and riskometer is one of SEBI's 6 levels
  - no chunk text contains return or performance figures
- **Exit codes:** `0` = all 27 fetched live, `1` = some came from snapshots, `2` = some scheme missing entirely.
- **Refresh:** run `python ingest.py` by hand or on a schedule (e.g. daily), then review the `corpus.json` diff in git before committing.

## 16. Configuration

| Variable | Default | Purpose |
|---|---|---|
| `BOLOSIP_HOST` / `BOLOSIP_PORT` | `127.0.0.1` / `8000` | Server bind address |
| `BOLOSIP_DB` | `data/bolosip.sqlite3` | Thread store path |
| `BOLOSIP_CORPUS` | `data/corpus.json` | Corpus path |
| `BOLOSIP_LLM` | `auto` | `auto` (on if credentials found) · `on` · `off` |
| `BOLOSIP_MODEL` | `llama-3.3-70b-versatile` | Groq model used for rephrasing |
| `BOLOSIP_RATE_MSG` / `BOLOSIP_RATE_ALL` | `30` / `120` | Per-IP limits per minute: messages / all requests (GAP-09) |
| `GROQ_API_KEY` | — | Groq API key, read by the SDK; never logged or committed |

## 17. Security and privacy

| Threat | Mitigation |
|---|---|
| User shares PAN, Aadhaar, OTP, etc. | Detected before anything else; reply declines. Only redacted text is stored; nothing goes to the LLM. |
| Personal data in logs | Request logging records method, path, status and timing only, never message bodies. |
| Prompt injection via the question ("ignore rules and recommend…") | Guards run first. The LLM sees only one trusted chunk, and its output is checked for numbers, URLs and advice words. Citations never come from the model. |
| Injected content in fetched pages | Only structured fields are taken from the embedded JSON, and every field becomes plain text in a template. Snapshots are data only. |
| XSS in the chat UI | `textContent` rendering only; links are built from the corpus, never from user text. |
| Oversized or abusive requests | Body, text-length and UUID limits; per-IP rate limit (GAP-09); server binds to localhost by default. |
| Other websites calling the local API (CSRF, DNS rebinding) | `Host` and `Origin` checks, JSON-only `POST` bodies, no CORS headers (GAP-08) |
| Another AMC's scheme answered with HDFC data | Other-AMC name check before alias matching (GAP-01) |
| Secrets in git | `.env` git-ignored; key read from the environment only. |
| Question text sent to a third party (Groq) | Only `answer` replies use the LLM, only after the personal-data guard, and only the question plus one public chunk are sent. `BOLOSIP_LLM=off` keeps everything local. |

## 18. Testing strategy

| Layer | File | What it covers | Acceptance criterion |
|---|---|---|---|
| Unit | `test_guards.py` | Positive and negative cases per guard, including tricky ones ("account statement", "BSE Sensex", "capital gains statement") | 4, 5, 6 |
| Unit | `test_retrieval.py` | Topic detection, alias resolution, the confusable groups in section 7, thresholds | 1, 7a, 8 |
| Unit | `test_format.py` | Sentence split with decimals and ₹, single URL, footer, LLM-output rejection | 2, 3 |
| Integration | `test_threads.py` | Two threads interleaved; follow-ups resolve per thread; PII stored redacted | 6, 7 |
| Acceptance | `test_acceptance.py` | 135 fact checks (5 facts × 27 schemes) compared against `data/raw` snapshots, at least 10 advice phrasings, returns questions, out-of-corpus questions | 1–8 |
| Manual | README checklist | UI shows welcome, 3 examples and the disclaimer on load | 9 |

All tests run with `python -m unittest` and need no network or LLM: the LLM is replaced by a stub. One optional test, marked `@skipUnless(credentials)`, makes real LLM calls to check that rephrasing passes the output checks.

## 19. Running locally

```bash
python ingest.py
```

```bash
python server.py
```

Then open http://127.0.0.1:8000.

To turn on LLM rephrasing, install the Groq SDK and set `GROQ_API_KEY` before starting the server:

```bash
pip install groq
```

To run the tests:

```bash
python -m unittest discover tests
```

## 20. Known limitations

- **Groww as the source of scheme facts.** This is required by the brief but is an aggregator, not the AMC. Mitigations: scheme facts are cross-checkable against HDFC's TER disclosure and factsheet, which are linked in general answers. A future version could take scheme facts straight from HDFC documents.
- **Freshness.** Answers are only as current as the last ingestion run. NAV and TER change often, and the footer date makes this visible.
- **Lexical retrieval.** Paraphrases with no shared words (e.g. "what does it cost me yearly") depend on the keyword synonyms. Missed questions get `not_found` rather than a wrong answer.
- **Regex guards.** These can miss unusual phrasings. They are tuned toward refusing, since a wrong refusal is safer than wrong advice.
- **English only.** Questions in Hindi or other languages are not supported.
- **Single-node.** SQLite and an in-process index suit one server, not a horizontally scaled deployment.

## 21. Decision log

| # | Decision | Alternatives considered | Reason |
|---|---|---|---|
| D1 | Python standard library server, no web framework | FastAPI, Flask | Zero install for the core app; the API is tiny |
| D2 | One fact per chunk, written at ingest time | Chunking raw page text | Makes citations exact and the extractive answer already correct |
| D3 | BM25 + boosts | Embeddings + vector DB | Small fixed corpus; deterministic and explainable (section 8.3) |
| D4 | LLM optional and rephrase-only | LLM generates the answer | Accuracy over intelligence; works offline and in tests |
| D5 | Guards before retrieval | Classify with the LLM | Deterministic, free, and personal data never leaves the process |
| D6 | Citation and footer added in code | Ask the model to cite | Guarantees exactly one valid link every time |
| D7 | SQLite for threads | In-memory dict, JSON files | Survives restarts, safe concurrent access, still zero install |
| D8 | Commit `corpus.json` to git | Build at deploy time only | Every data change is reviewable as a diff |
| D9 | Reject other-AMC names before alias matching (GAP-01) | Require "HDFC" in every question | Users rarely type "HDFC"; a name list keeps short questions working and stops wrong-AMC answers |
| D10 | `help` reply kind with no link (GAP-02) | Treat greetings as `not_found` | A greeting states no fact, so a citation would be meaningless |
| D11 | Origin and Host checks instead of auth tokens (GAP-08) | Login or API key | Keeps "no login" (PS §7) while stopping other sites from using the local API |
| D12 | Groq as the optional LLM provider | Anthropic Claude, OpenAI, local model | Project choice: fast, low-cost hosted open-weight models; the rephrase-only design means any provider can be swapped behind `llm.py` |

## 22. Future work

- Take scheme facts directly from HDFC Mutual Fund documents (SID/KIM, TER disclosure, factsheet PDF) and use Groww only as a cross-check.
- Run ingestion on a schedule, with an alert when a fact changes by more than a threshold.
- An optional embedding retriever behind the same `Retriever` interface, compared against the acceptance set.
- Answers in Hindi built from the same extractive chunks.
- An admin view listing `not_found` questions, to grow keyword synonyms and the official notes.
