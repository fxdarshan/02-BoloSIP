# BoloSIP — Mutual Fund FAQ Assistant (Facts-Only Q&A)

> **Facts-only. No investment advice.**

Version 2 · 16 Nov 2026 · The original brief is kept unchanged in [`problem_statement_original.txt`](problem_statement_original.txt).

---

## 1. Problem

Retail investors and support teams ask the same factual questions about mutual fund schemes again and again: *What is the expense ratio? Is there an exit load? What is the minimum SIP?* The answers exist in public documents, but they are scattered across fund-house pages, factsheets and regulator sites, and many chatbots mix facts with opinions or recommendations.

**BoloSIP** is a small Retrieval-Augmented Generation (RAG) assistant that answers only objective, verifiable questions about a fixed set of HDFC Mutual Fund schemes. Every answer is short, cites exactly one source, and shows when that source was last read. It never gives investment advice.

**Guiding principle:** accuracy over intelligence. If BoloSIP is not sure, it says so and points to the source rather than guessing.

## 2. Users

| User | What they need |
|---|---|
| Retail investor comparing schemes | Quick, trustworthy facts with a link to check them |
| Customer support / content team | Consistent answers to repetitive questions, ready to paste |

## 3. Scope

### 3.1 AMC and schemes (the corpus)

One AMC: **HDFC Mutual Fund**. Five schemes, all Direct plan, Growth option:

| # | Scheme | Category | Scheme page (data source) |
|---|---|---|---|
| 1 | HDFC Large Cap Fund | Equity – Large Cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 2 | HDFC Mid Cap Fund | Equity – Mid Cap | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| 3 | HDFC Small Cap Fund | Equity – Small Cap | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| 4 | HDFC Multi Cap Fund | Equity – Multi Cap | https://groww.in/mutual-funds/hdfc-multi-cap-fund-direct-growth |
| 5 | HDFC Silver ETF FoF | Fund of Funds – Silver | https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth |

> None of these five schemes is an ELSS (tax-saving) scheme. ELSS lock-in questions are answered with the general rule from an official source, and the answer says that none of the covered schemes is ELSS.

### 3.2 Source policy

| Kind of question | Allowed sources |
|---|---|
| Scheme facts (expense ratio, exit load, minimum SIP, riskometer, benchmark, fund manager, NAV, AUM) | The five scheme pages above, as prescribed by this brief. Where the same fact is on an HDFC Mutual Fund page (factsheet, SID/KIM, TER disclosure), that page may be cited instead. |
| Processes (download a statement, capital gains report) | HDFC Mutual Fund, its registrar CAMS, or MF Central |
| Concepts and education (what is an exit load, riskometer levels, ELSS rules) | AMFI, SEBI, HDFC Mutual Fund |
| Performance and returns | HDFC Mutual Fund's official factsheet page, as a link only |

Never used: third-party blogs, news sites, forums, or other aggregator content.

> **Note on the Groww pages:** Groww is an aggregator. This brief nevertheless names its scheme pages as the data source, using Groww as the reference product. Those pages are therefore the one allowed exception, used only for scheme facts. The README must call this out as a known limitation.

### 3.3 Questions BoloSIP must answer

| Topic | Example question |
|---|---|
| Expense ratio | "What is the expense ratio of HDFC Mid Cap Fund?" |
| Exit load | "Is there an exit load on the Silver ETF FoF?" |
| Minimum SIP / lump sum | "What is the minimum SIP for HDFC Small Cap?" |
| Lock-in (ELSS rule) | "What is the ELSS lock-in period?" |
| Riskometer | "What is the riskometer level of HDFC Large Cap?" |
| Benchmark | "Which index does HDFC Multi Cap track?" |
| Fund manager, NAV, AUM, launch date, ISIN | "Who manages HDFC Mid Cap Fund?" |
| Statements | "How do I download my account statement?" |
| Capital gains report | "Where can I get a capital gains statement?" |

### 3.4 Out of scope (non-goals)

- Investment advice, recommendations, suitability, "best fund" rankings
- Return calculations, performance comparisons, projections, SIP calculators
- Any AMC or scheme beyond the five listed
- Transactions, logins, account lookups, or anything that needs personal data
- Tax advice (BoloSIP may link to an official page, but does not interpret anyone's tax position)

## 4. Response rules

### 4.1 Factual answer

Every factual answer must:

1. Be **at most 3 sentences**.
2. Include **exactly one** source link: the page the fact came from.
3. End with the footer **`Last updated from sources: <DD Mon YYYY>`**, the date that source was last fetched or reviewed.
4. Use only facts found in the retrieved source text: no outside knowledge, opinion or adjectives such as "good" or "low".

**Example**

> The expense ratio (TER) of HDFC Mid Cap Fund Direct Growth is 0.73% per annum, as on 12 Nov 2026.
> Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth
> Last updated from sources: 16 Nov 2026

### 4.2 Decision rules for every message

Checks run in this order. The first one that matches decides the reply.

| # | Situation | How to detect | Reply |
|---|---|---|---|
| 1 | Personal data in the message (PAN, Aadhaar, account or folio number, OTP, email, phone) | Pattern match | Politely decline. Say BoloSIP does not need or store personal details. **Do not store the raw message**; save only a redacted version. |
| 2 | Advisory or opinion question ("Should I invest?", "Which is better?", "Is it safe?") | Intent check | Polite refusal that restates the facts-only limit, plus one educational link (AMFI or SEBI). |
| 3 | Performance or returns question ("What were the 3-year returns?") | Intent check | No numbers. One sentence pointing to the official HDFC factsheet, plus its link. |
| 4 | Scheme-specific question with no scheme named | No scheme found in the message or earlier in the thread | Ask which of the five schemes the user means. |
| 5 | Question not covered by the corpus | Retrieval confidence below threshold | Say the information is not in BoloSIP's sources, with a link to the closest official page. Never guess. |
| 6 | Covered factual question | Otherwise | Factual answer per 4.1. |

**Refusal example**

> I can only share factual information about these schemes, so I can't advise whether you should invest. For guidance on choosing mutual funds, see AMFI's investor education resources.
> Source: https://www.amfiindia.com/investor
> Last updated from sources: 16 Nov 2026

## 5. User interface (minimal)

A single web page with:

- A **welcome message** explaining what BoloSIP can answer
- **Three clickable example questions**
- The **disclaimer "Facts-only. No investment advice."**, always visible, not just on first load
- A **thread list** for creating, switching between and deleting conversations
- Each answer shows its source as a clickable link and its "Last updated" footer

## 6. Multiple chat threads

- Users can have several independent conversations open at once. Each thread keeps its own history.
- Follow-ups use context from **their own thread only**. For example, after asking about HDFC Mid Cap, "what about its exit load?" refers to HDFC Mid Cap in that thread and nowhere else.
- Concurrent requests from different threads must not mix up answers or history.
- Thread history is saved on the server so it survives a page reload, and saved with personal data already redacted (see 4.2, rule 1).

## 7. Privacy and security

BoloSIP must not collect, store or process:

- PAN or Aadhaar numbers
- Bank account or folio numbers
- OTPs
- Email addresses or phone numbers

Also:

- No login and no user tracking.
- Any LLM API key is read from the environment, never committed to the repository.
- Messages containing personal data are not sent to any LLM.

## 8. Data freshness

- Scheme facts are rebuilt by running the ingestion script, which re-fetches the five scheme pages.
- Each stored fact keeps its source URL and the date it was fetched. That date is what the answer footer shows.
- Hand-curated notes from official sources carry a "reviewed on" date, updated whenever they are rechecked.

## 9. Deliverables

1. **Working assistant**: RAG backend plus the minimal web UI, with multi-thread support.
2. **README** covering:
   - Setup and run instructions
   - The selected AMC and schemes
   - Architecture overview: ingestion → chunks → retrieval → answer composition → guards
   - Known limitations, including the Groww source exception (3.2) and data freshness
3. **Disclaimer snippet**: "Facts-only. No investment advice."
4. **Test set**: the questions in section 10, runnable automatically.

## 10. Acceptance criteria

The build is accepted when an automated test run shows all of the following:

| # | Criterion | Check |
|---|---|---|
| 1 | Correct facts | Expense ratio, exit load, minimum SIP, riskometer and benchmark for all 5 schemes match the source page (25 questions). |
| 2 | Answer format | 100% of answers have 3 sentences or fewer, exactly one URL, and the footer. |
| 3 | Valid citations | Every cited URL is on the allowed-source list (3.2). |
| 4 | Refusals | At least 10 advisory phrasings ("should I invest", "which is better", "is it safe", "X vs Y", …) are all refused with an AMFI or SEBI link. |
| 5 | Performance handling | Returns questions get the factsheet link and contain no return figures. |
| 6 | Privacy | Messages with a sample PAN, Aadhaar, email, phone or OTP are declined, and the stored thread holds only the redacted text. |
| 7 | Threads | Two threads asking about different schemes give correct follow-up answers without crossing over. |
| 8 | No guessing | Questions outside the corpus (e.g. a scheme from another AMC) get a "not in my sources" reply, not a made-up answer. |
| 9 | UI | Welcome message, three example questions and the disclaimer are visible on load. |

## 11. Known constraints and assumptions

- Groww pages may change layout or block automated fetching. Ingestion should keep the last good copy of each page and fall back to it.
- Facts such as NAV, AUM and expense ratio change often. Answers are only as fresh as the last ingestion run, which the footer makes visible.
- An LLM may be used to phrase answers, but only from retrieved text. The system must still work without one, by giving the retrieved fact directly.

## 12. Glossary

| Term | Meaning |
|---|---|
| AMC | Asset Management Company: the fund house (here, HDFC Mutual Fund) |
| AMFI | Association of Mutual Funds in India |
| SEBI | Securities and Exchange Board of India, the market regulator |
| TER / expense ratio | Annual fee charged by a scheme, as a % of its assets |
| Exit load | Charge deducted when units are redeemed before a set period |
| Riskometer | SEBI's 6-level risk label for every scheme (Low to Very High) |
| ELSS | Equity Linked Savings Scheme: tax-saving fund with a 3-year lock-in |
| SIP | Systematic Investment Plan: investing a fixed amount at regular intervals |
| RTA | Registrar and Transfer Agent (CAMS for HDFC Mutual Fund) |
| CAS | Consolidated Account Statement across fund houses |
| RAG | Retrieval-Augmented Generation: find the relevant source text first, then answer only from it |
