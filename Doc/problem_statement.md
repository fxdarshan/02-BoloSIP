# BoloSIP — Mutual Fund FAQ Assistant (Facts-Only Q&A)

> **Facts-only. No investment advice.**

Version 2.3 · 22 Nov 2026 · Daily scheduled data refresh · v2.2: corpus expanded from 5 to 27 schemes · Optional LLM provider: Groq · The original brief is kept unchanged in [`problem_statement_original.txt`](problem_statement_original.txt).

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

One AMC: **HDFC Mutual Fund**. 27 schemes, all Direct plan, Growth option. Names and categories are as shown on each scheme page (checked 16 Nov 2026).

**Equity (16)**

| # | Scheme | Category | Scheme page (data source) |
|---|---|---|---|
| 1 | HDFC Large Cap Fund | Large Cap | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 2 | HDFC Mid Cap Fund | Mid Cap | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| 3 | HDFC Small Cap Fund | Small Cap | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| 4 | HDFC Large & Mid Cap Fund | Large & Mid Cap | https://groww.in/mutual-funds/hdfc-large-mid-cap-fund-direct-growth |
| 5 | HDFC Multi Cap Fund | Multi Cap | https://groww.in/mutual-funds/hdfc-multi-cap-fund-direct-growth |
| 6 | HDFC Flexi Cap Fund ¹ | Flexi Cap | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 7 | HDFC Focused Fund | Focused | https://groww.in/mutual-funds/hdfc-focused-fund-direct-growth |
| 8 | HDFC NIFTY 50 Index Fund | Index (Large Cap) | https://groww.in/mutual-funds/hdfc-nifty-50-index-fund-direct-growth |
| 9 | HDFC BSE Sensex Index Fund | Index (Large Cap) | https://groww.in/mutual-funds/hdfc-bse-sensex-index-fund-direct-growth |
| 10 | HDFC Pharma and Healthcare Fund | Sectoral | https://groww.in/mutual-funds/hdfc-pharma-and-healthcare-fund-direct-growth |
| 11 | HDFC Technology Fund | Sectoral | https://groww.in/mutual-funds/hdfc-technology-fund-direct-growth |
| 12 | HDFC Transportation and Logistics Fund | Sectoral | https://groww.in/mutual-funds/hdfc-transportation-and-logistics-fund-direct-growth |
| 13 | HDFC Defence Fund | Thematic | https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth |
| 14 | HDFC Housing Opportunities Fund | Thematic | https://groww.in/mutual-funds/hdfc-housing-opportunities-fund-direct-growth |
| 15 | HDFC Business Cycle Fund | Thematic | https://groww.in/mutual-funds/hdfc-business-cycle-fund-direct-growth |
| 16 | HDFC Infrastructure Fund | Thematic | https://groww.in/mutual-funds/hdfc-infrastructure-fund-direct-growth |

¹ The page URL still uses the scheme's former name, "HDFC Equity Fund". BoloSIP must recognise both names.

**Hybrid (4)**

| # | Scheme | Category | Scheme page (data source) |
|---|---|---|---|
| 17 | HDFC Balanced Advantage Fund | Dynamic Asset Allocation | https://groww.in/mutual-funds/hdfc-balanced-advantage-fund-direct-growth |
| 18 | HDFC Multi Asset Allocation Fund | Multi Asset Allocation | https://groww.in/mutual-funds/hdfc-multi-asset-allocation-fund-direct-growth |
| 19 | HDFC Equity Savings Fund | Equity Savings | https://groww.in/mutual-funds/hdfc-equity-savings-fund-direct-growth |
| 20 | HDFC Arbitrage Fund | Arbitrage | https://groww.in/mutual-funds/hdfc-arbitrage-fund-direct-growth |

**Debt (6)**

| # | Scheme | Category | Scheme page (data source) |
|---|---|---|---|
| 21 | HDFC Overnight Fund | Overnight | https://groww.in/mutual-funds/hdfc-overnight-fund-direct-growth |
| 22 | HDFC Liquid Fund | Liquid | https://groww.in/mutual-funds/hdfc-liquid-fund-direct-growth |
| 23 | HDFC Money Market Fund | Money Market | https://groww.in/mutual-funds/hdfc-money-market-fund-direct-growth |
| 24 | HDFC Ultra Short Term Fund | Ultra Short Term | https://groww.in/mutual-funds/hdfc-ultra-short-term-fund-direct-growth |
| 25 | HDFC Banking and PSU Debt Fund | Banking and PSU Debt | https://groww.in/mutual-funds/hdfc-banking-and-psu-debt-fund-direct-growth |
| 26 | HDFC Gilt Fund | Gilt | https://groww.in/mutual-funds/hdfc-gilt-fund-direct-growth |

**Fund of Funds (1)**

| # | Scheme | Category | Scheme page (data source) |
|---|---|---|---|
| 27 | HDFC Silver ETF FoF | FoF – Silver | https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth |

> None of these 27 schemes is an ELSS (tax-saving) scheme. ELSS lock-in questions are answered with the general rule from an official source, and the answer says that none of the covered schemes is ELSS.
>
> Some schemes have similar names, such as Large Cap / Large & Mid Cap / NIFTY 50 Index / BSE Sensex Index, Equity Savings / Flexi Cap ("HDFC Equity"), and Liquid / Money Market / Overnight. Where a name could mean more than one scheme, BoloSIP must ask which one the user means rather than guess.

### 3.2 Source policy

| Kind of question | Allowed sources |
|---|---|
| Scheme facts (expense ratio, exit load, minimum SIP, riskometer, benchmark, fund manager, NAV, AUM) | The 27 scheme pages above, as prescribed by this brief. Where the same fact is on an HDFC Mutual Fund page (factsheet, SID/KIM, TER disclosure), that page may be cited instead. |
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
- Any AMC or scheme beyond the 27 listed
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
| 4 | Scheme-specific question with no scheme named, or a name that matches more than one scheme | No single scheme found in the message or earlier in the thread | Ask which of the 27 schemes the user means. |
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

- Scheme facts are rebuilt by the ingestion script, which re-fetches the 27 scheme pages. A scheduled job runs it **every day at 10:00 IST** and publishes the new data only if every check passes; it can also be run by hand.
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
| 1 | Correct facts | Expense ratio, exit load, minimum SIP, riskometer and benchmark for all 27 schemes match the source page (5 facts × 27 schemes = 135 checks). |
| 2 | Answer format | 100% of answers have 3 sentences or fewer, exactly one URL, and the footer. |
| 3 | Valid citations | Every cited URL is on the allowed-source list (3.2). |
| 4 | Refusals | At least 10 advisory phrasings ("should I invest", "which is better", "is it safe", "X vs Y", …) are all refused with an AMFI or SEBI link. |
| 5 | Performance handling | Returns questions get the factsheet link and contain no return figures. |
| 6 | Privacy | Messages with a sample PAN, Aadhaar, email, phone or OTP are declined, and the stored thread holds only the redacted text. |
| 7 | Threads | Two threads asking about different schemes give correct follow-up answers without crossing over. |
| 7a | Similar names | Ambiguous names (e.g. "HDFC Equity", "HDFC large cap index") get a clarifying question; "HDFC Equity Fund" and "HDFC Flexi Cap Fund" both resolve to the same scheme where unambiguous. |
| 8 | No guessing | Questions outside the corpus (e.g. a scheme from another AMC) get a "not in my sources" reply, not a made-up answer. |
| 9 | UI | Welcome message, three example questions and the disclaimer are visible on load. |

## 11. Known constraints and assumptions

- Groww pages may change layout or block automated fetching. Ingestion should keep the last good copy of each page and fall back to it.
- Facts such as NAV, AUM and expense ratio change often. Answers are only as fresh as the last ingestion run, which the footer makes visible.
- An LLM may be used to phrase answers, but only from retrieved text. The system must still work without one, by giving the retrieved fact directly.
- The LLM provider is **Groq** (`groq` Python SDK, key in `GROQ_API_KEY`). Groq is a third-party service, so only the question and one public source chunk are ever sent to it, never personal data.

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
