# BoloSIP: Retrieval Research for Phase 3

> **Facts-only. No investment advice.**

Version 1.0 · 18 Nov 2026 · Input to Phase 3 of [Implementation-plan.md](Implementation-plan.md) · Decisions recorded in [architecture.md](architecture.md) v1.3

---

## 1. Question

Phase 3 builds scheme resolution and retrieval. Before building it, this research answers three questions using the real corpus (`data/corpus.json`, built in Phase 1) and real question sets:

1. **Chunking strategy:** is the fact-level chunking from Phase 1 right, and what text should be embedded?
2. **Embedding model:** do embeddings beat the keyword search (BM25) the architecture planned, and if so, which model?
3. **Vector database:** where should the vectors live and how should they be searched?

Everything here is reproducible: the scripts, question set and raw results are in [`eval/research/`](../eval/research/) (§8).

## 2. Summary of decisions

| Decision | Choice | Main evidence |
|---|---|---|
| Chunking | Keep **one chunk per fact** (templated, 1–2 sentences); no splitting, no overlap | Median 19 words, max 70 words / 489 chars, far below any model's limit; each chunk already answers exactly one question |
| Text that gets embedded | `search_document: {fact text} {topic keywords}` | Best variant for the chosen model: 93% vs 83% with a topic header (both with prefixes); text alone scored 74% (measured without prefixes) |
| Embedding model | **`nomic-ai/nomic-embed-text-v1.5`**, run locally via **fastembed** (ONNX, CPU, no PyTorch), with `search_query:` / `search_document:` prefixes | 93% top-1 on user wording vs **69%** for BM25; 100% on template wording and general questions; 100% of out-of-scope questions rejected |
| Fallback | Keep **BM25** (text + keywords) when the embedding model isn't available | App still runs on Python 3.15 and in offline tests; 96% on template wording |
| Retrieval | Dense cosine similarity, **filtered to the resolved scheme's 12 facts + the 10 official notes** | Same-topic chunks of different schemes are 50–70% identical, so scheme must come from the name resolver, not similarity |
| Hybrid (BM25 + embeddings, RRF) | **Rejected** | Lowered general-question accuracy (100% → 83%) and out-of-scope rejection (100% → 79%) |
| Vector store | Research recommended **no vector database** (1 MB numpy matrix, exact search). **Owner's decision (18 Nov 2026): local ChromaDB**, rebuilt from the committed `.npy` vectors (architecture §8.4) | 0.03 ms per exact search; Chroma's HNSW returns the same top hits at this size, so accuracy is unaffected |
| Score threshold | Start at **cosine 0.74** (tune in Phase 8) | Highest out-of-scope score 0.73; 5th-percentile real question 0.76 |

## 3. What the data looks like

| Property | Value | What it means |
|---|---|---|
| Chunks | 334 (27 schemes × 12 facts + 10 official notes) | Tiny corpus |
| Words per chunk | min 11, median 19, mean 23, max 70 | One fact each; no chunk needs splitting |
| Sentences per chunk | 245 have 1, 89 have 2 | Already within the 3-sentence answer limit |
| Vocabulary | 597 distinct words | Very narrow domain |
| Same-topic overlap across schemes | expense ratio 0.71, riskometer 0.69, benchmark 0.54, category 0.53, fund manager 0.49, exit load 0.47 (word Jaccard) | Chunks for different schemes look almost the same; similarity alone can't tell schemes apart |
| Scheme-name words shared | "cap" (6 schemes), "large", "mid", "multi", "index", "and" (2–4 each) | The name resolver (Phase 3) must handle these, not the retriever |
| Question length | 6–10 words (median) | Short queries |

**Consequence:** retrieval is really two separate jobs. *Which scheme?* is a name-matching problem, solved by the alias resolver. *Which fact about it?* means choosing among about 21 topics, where wording varies a lot ("how much does it charge every year" = expense ratio). Embeddings help the second job.

## 4. Test sets

| Set | Size | Wording | Purpose |
|---|---|---|---|
| `facts.jsonl` (Phase 1) | 324 | Template wording ("What is the expense ratio of …?") | Baseline; flatters keyword search |
| `general.jsonl` (Phase 2 audit) | 23 | Process and definition questions | Official-note retrieval |
| **`retrieval_probe.jsonl`** (new) | 72 + 14 | **How users actually ask** ("annual fee", "penalty if I withdraw early", "who runs it") + 14 out-of-scope questions | The real test of understanding |

Measured: **top-1 accuracy**, meaning the right chunk ranked first. It's measured both without a scheme filter and with the scheme filter Phase 3 will apply (that scheme's 12 facts plus the 10 official notes). Also measured: **out-of-scope rejection**, the share of the 14 unrelated questions whose top score falls below a threshold that keeps 95% of real questions.

> **Caveat:** the probe set was used to *choose* the model, so it is no longer an unbiased test. Phase 3 must build a fresh held-out set (`holdout.jsonl`, as `eval.md` requires) and confirm the result there.

## 5. Results

### 5.1 Full comparison (top-1 with scheme filter)

| Method | Embedded text | Template wording | General | **User wording** | Out-of-scope rejected |
|---|---|---|---|---|---|
| BM25 | text | 80% | 70% | 49% | 79% |
| BM25 (current plan) | text + keywords | 96% | 83% | **69%** | 93% |
| all-MiniLM-L6-v2 (22M) | enriched | 97% | 91% | 76% | 93% |
| bge-small-en-v1.5 (33M, quantised) | enriched | 98% | 100% | 83% | 93% |
| snowflake-arctic-embed-s (33M) | enriched | 99% | 83% | 78% | 100% |
| bge-base-en-v1.5 (110M, quantised) | enriched + query instruction | 100% | 96% | 90% | 93% |
| nomic-embed-text-v1.5 (137M) | text + keywords, no prefixes | 100% | 100% | 90% | 100% |
| **nomic-embed-text-v1.5** | **text + keywords, with prefixes** | **100%** | **100%** | **93%** | **100%** |
| nomic-embed-text-v1.5-Q (quantised) | text + keywords | 97% | 100% | 81% | 100% |
| Hybrid RRF: BM25 + nomic | text + keywords | 98% | 83% | 82% | 79% |
| Hybrid RRF: BM25 + bge-base | enriched | 98% | 83% | 85% | 79% |

"Enriched" means a topic header before the fact (e.g. "Exit load: charge on early redemption. …"). Full results for all 33 combinations, with and without the scheme filter, are in `retrieval_results.json`.

### 5.2 Chunk-text variants (what to embed)

| Model | Text only | Text + keywords | Topic header + text |
|---|---|---|---|
| BM25 | 49% | **69%** | 62% |
| bge-small | 47% | 75% | **83%** |
| bge-base | 68% | 86% | **89%** |
| nomic (with prefixes) | 74% (without prefixes) | **93%** | 83% |

Adding the topic keywords from Phase 1 helps every method. The best text depends on the model, so the choice is fixed together with the model.

### 5.3 Speed and size (CPU, this laptop)

| Method | Model on disk | Load | Embed all 334 chunks | Per question |
|---|---|---|---|---|
| BM25 | — | — | 9 ms (index) | 0.4 ms |
| bge-small (quantised) | 67 MB | 0.6 s | 9 s | 7 ms |
| bge-base (quantised) | 218 MB | 1.4 s | 28 s | 24 ms |
| **nomic-embed-text-v1.5** | **548 MB** | **1.6 s** | **41 s** (once, at ingestion) | **29 ms** |
| Exact search over the 1 MB matrix | — | — | — | 0.03 ms |

Embedding the corpus happens once, at ingestion, and the vectors are saved. Per-question cost (about 30 ms) is well within an interactive chat.

### 5.4 What still fails (nomic, 5 of 72)

| Question | Expected | Got | Rank of the right fact |
|---|---|---|---|
| "management fee of HDFC Small Cap" | expense ratio | fund manager | 3 |
| "what does the HDFC Nifty 50 index fund track" | benchmark | category | 2 |
| "against what is HDFC Pharma and Healthcare measured" | benchmark | riskometer | 2 |
| "how long is my money stuck in HDFC Equity Savings Fund" | lock-in | exit load | 2 |
| "monthly fund report download" | factsheet | statement | 2 |

All five are near-misses between neighbouring topics, caused by vocabulary. Each is fixable by adding the missing words to that topic's keywords (e.g. "track", "measured against", "management fee", "stuck", "monthly report"), which are embedded with the fact. Phase 3 does this and re-measures on the held-out set.

### 5.5 Out-of-scope separation (nomic)

| | Top cosine score |
|---|---|
| Real questions: minimum / 5th percentile / median | 0.678 / 0.762 / 0.878 |
| Out-of-scope: highest | 0.730 ("HDFC Bank fixed deposit interest rate") |
| Next highest | 0.700 ("change the bank account linked to my folio"), 0.692 ("CEO of HDFC AMC") |

A threshold of **0.74** rejects all 14 out-of-scope questions and keeps about 95% of real ones. The margin is small, so the score is not the only defence. The resolver's other-fund-house and non-fund-HDFC checks (GAP-01, SCH-17) catch "HDFC Bank…" earlier. A real question that falls under the threshold gets a "not in my sources" reply, never a wrong answer.

## 6. Vector store options

| Option | Fit for 334 × 768 vectors | Verdict |
|---|---|---|
| numpy matrix in `data/embeddings.npy`, exact cosine | 1 MB, 0.03 ms, deterministic, diffable by hash | Research's recommendation; kept as the committed copy of the vectors |
| sqlite-vec | Single file, but needs a loadable SQLite extension (fragile on Windows Python builds) | Upgrade path if the corpus reaches tens of thousands of chunks |
| FAISS | Fast approximate search for millions of vectors; platform-specific wheels | Overkill |
| **Chroma** (local, embedded) | Embedded database, many dependencies (84 packages), own storage format; no Python 3.15 build | **Chosen by the project owner** for a real vector DB that can grow; local, telemetry off |
| LanceDB | Embedded database with its own storage format | Not needed |
| Qdrant / Weaviate / Pinecone | Separate server or cloud service | Overkill; adds operations and sends data off the laptop |

Exact search also means results never vary between runs (approximate indexes can), which keeps the evaluation reproducible. With Chroma chosen, a test checks that Chroma's top hits equal exact search over the `.npy` copy.

## 7. Constraints and how the design handles them

| Constraint | Handling |
|---|---|
| **Groq has no embeddings endpoint** (its models page lists only chat and speech models) | Embeddings run locally; questions never leave the laptop for retrieval |
| **onnxruntime has no Python 3.15 build yet**, and the laptop's default Python is 3.15 | Embeddings are an optional extra (`pip install .[embed]`, needs Python 3.10–3.14). On 3.15, or without the model, BoloSIP falls back to BM25 and says so in `/api/health`. Recommended: run BoloSIP in a `uv` Python 3.12 environment |
| Model download (548 MB) on first use | Cached under `.cache/models/` in the project (git-ignored) instead of the system temp folder |
| Vectors must match the corpus | `data/embeddings.json` records the model ID, prefixes, dimensions, chunk-ID order and a SHA-256 hash of `corpus.json`. On mismatch the app refuses to use the vectors and falls back to BM25 |
| Default tests must stay offline and fast | Default tests use BM25 and a tiny stub embedder. Real-model tests run only when the model is cached, plus a CI job on Python 3.12 that caches the model |
| Model licence | nomic-embed-text-v1.5: Apache 2.0 |

## 8. Reproducing this research

```bash
uv venv --python 3.12 .venv-research
```

```bash
uv pip install --python .venv-research/Scripts/python.exe fastembed numpy
```

```bash
.venv-research/Scripts/python.exe eval/research/retrieval_benchmark.py
```

| File | Content |
|---|---|
| `eval/research/retrieval_probe.jsonl` | 72 user-wording questions + 14 out-of-scope questions |
| `eval/research/retrieval_benchmark.py` → `retrieval_results.json` | All methods × chunk-text variants |
| `eval/research/retrieval_followup.py` → `retrieval_followup.json` | Shortlist: failures, size, speed, quantised model |
| `eval/research/retrieval_prefix_check.py` → `retrieval_prefix_check.json` | Effect of nomic prefixes and the bge query instruction |
