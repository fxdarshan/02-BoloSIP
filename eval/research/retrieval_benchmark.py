"""Retrieval research for Phase 3: BM25 vs embedding models vs hybrid, and chunk-text variants.

Not part of the app or the default test run. Needs `fastembed` (ONNX, no PyTorch),
which has no Python 3.15 build yet, so run it in a separate Python 3.12 env:

    uv venv --python 3.12 .venv-research
    uv pip install --python .venv-research/Scripts/python.exe fastembed numpy
    .venv-research/Scripts/python.exe eval/research/retrieval_benchmark.py

Writes eval/research/retrieval_results.json and prints Markdown tables.
"""
from __future__ import annotations

import json
import math
import re
import statistics as st
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bolosip.topics import TOPIC_KEYWORDS  # noqa: E402

OUT = ROOT / "eval" / "research" / "retrieval_results.json"
MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",   # 22M params, 384 dims
    "BAAI/bge-small-en-v1.5",                   # 33M, 384
    "snowflake/snowflake-arctic-embed-s",       # 33M, 384
    "BAAI/bge-base-en-v1.5",                    # 110M, 768
    "nomic-ai/nomic-embed-text-v1.5",           # 137M, 768
]
# Topic labels used only for the "enriched" chunk variant (not taken from any test set).
TOPIC_LABEL = {
    "expense_ratio": "Expense ratio / TER: annual cost of the scheme",
    "exit_load": "Exit load: charge on early redemption or withdrawal",
    "min_investment": "Minimum investment: smallest SIP and lump-sum amount",
    "riskometer": "Riskometer: SEBI risk level of the scheme",
    "benchmark": "Benchmark: index the scheme is measured against",
    "lock_in": "Lock-in: whether money can be withdrawn any time",
    "fund_manager": "Fund manager: who manages the scheme",
    "category": "Category and objective: what the scheme invests in",
    "nav": "NAV: price of one unit",
    "aum": "AUM: fund size, total assets",
    "scheme_details": "Scheme details: launch date, ISIN, registrar",
    "stamp_duty": "Stamp duty on purchases",
    "statement": "Account statement download",
    "capital_gains": "Capital gains statement for tax",
    "lock_in_general": "ELSS lock-in rule",
    "riskometer_general": "Riskometer levels explained",
    "expense_ratio_general": "What expense ratio (TER) means",
    "exit_load_general": "What an exit load means",
    "plans_general": "Direct plan vs regular plan",
    "sip_general": "What a SIP is",
    "factsheet": "Factsheet: holdings, portfolio, monthly report",
}
STOP = set("a an the of for to in on is are was be it its this that what which who how do does did i my me "
           "can could would should will there any by with at from as and or about tell please".split())


def tok(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP]


def doc_text(c: dict, variant: str) -> str:
    if variant == "text":
        return c["text"]
    if variant == "text+keywords":
        return f"{c['text']} {c['keywords']}"
    return f"{TOPIC_LABEL[c['topic']]}. {c['text']}"          # "enriched": topic header + fact


class BM25:
    def __init__(self, docs: list[str], k1=1.5, b=0.75):
        self.toks = [tok(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = st.mean(len(t) for t in self.toks)
        df = Counter(w for t in self.toks for w in set(t))
        n = len(docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.tf = [Counter(t) for t in self.toks]

    def scores(self, q: str) -> np.ndarray:
        qs = tok(q)
        out = np.zeros(len(self.toks))
        for i, (tf, t) in enumerate(zip(self.tf, self.toks)):
            s = 0.0
            for w in qs:
                f = tf.get(w)
                if f:
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(t) / self.avg))
            out[i] = s
        return out


def load_cases(chunks: list[dict]) -> dict[str, list[dict]]:
    def jl(p):
        return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]
    facts = [{"q": c["question"], "scheme": c["expect"]["scheme_id"], "topic": c["expect"]["topic"]}
             for c in jl(ROOT / "eval/datasets/facts.jsonl")]
    general = [{"q": c["question"], "scheme": None, "topic": c["expect"]["topic"]}
               for c in jl(ROOT / "eval/datasets/general.jsonl")]
    probe = jl(ROOT / "eval/research/retrieval_probe.jsonl")
    probe_pos = [{"q": c["question"], "scheme": c["scheme"], "topic": c["topic"]} for c in probe if c["topic"]]
    probe_neg = [{"q": c["question"], "scheme": None, "topic": None} for c in probe if not c["topic"]]
    return {"facts (template wording)": facts, "general (official notes)": general,
            "probe (user wording)": probe_pos, "_neg": probe_neg}


def evaluate(score_fn, chunks, cases):
    """Top-1 accuracy without and with the scheme filter Phase 3 will provide."""
    ids = [(c["scheme_id"], c["topic"]) for c in chunks]
    official = np.array([c["scheme_id"] is None for c in chunks])
    res = {}
    for name, qs in cases.items():
        if name == "_neg":
            continue
        hit_all = hit_filt = 0
        for case in qs:
            s = score_fn(case["q"])
            gold = (case["scheme"], case["topic"])
            if ids[int(np.argmax(s))] == gold:
                hit_all += 1
            if case["scheme"]:
                mask = official | np.array([c["scheme_id"] == case["scheme"] for c in chunks])
            else:
                mask = np.ones(len(chunks), bool)
            s2 = np.where(mask, s, -np.inf)
            if ids[int(np.argmax(s2))] == gold:
                hit_filt += 1
        res[name] = {"top1_no_filter": hit_all / len(qs), "top1_scheme_filter": hit_filt / len(qs), "n": len(qs)}
    # Out-of-scope separability: can one threshold on the top score reject negatives?
    pos = [float(np.max(score_fn(c["q"]))) for n, qs in cases.items() if n != "_neg" for c in qs]
    neg = [float(np.max(score_fn(c["q"]))) for c in cases["_neg"]]
    thr = sorted(pos)[int(0.05 * len(pos))]                       # keeps 95% of real questions
    res["out_of_scope"] = {"neg_rejected_at_95pct_recall": sum(n < thr for n in neg) / len(neg),
                           "pos_median": st.median(pos), "neg_max": max(neg)}
    return res


def main():
    from fastembed import TextEmbedding

    corpus = json.loads((ROOT / "data/corpus.json").read_text(encoding="utf-8"))
    chunks = corpus["chunks"]
    cases = load_cases(chunks)
    results = {"n_chunks": len(chunks), "methods": {}}

    for variant in ("text", "text+keywords", "enriched"):
        t0 = time.perf_counter()
        bm = BM25([doc_text(c, variant) for c in chunks])
        build = time.perf_counter() - t0
        t0 = time.perf_counter()
        r = evaluate(bm.scores, chunks, cases)
        r["build_ms"] = build * 1000
        r["query_ms"] = (time.perf_counter() - t0) / sum(len(v) for v in cases.values()) / 3 * 1000
        results["methods"][f"BM25 | {variant}"] = r
        print("done", f"BM25 | {variant}", flush=True)

    bm_kw = BM25([doc_text(c, "text+keywords") for c in chunks])
    for model_name in MODELS:
        try:
            t0 = time.perf_counter()
            model = TextEmbedding(model_name=model_name)
            load_s = time.perf_counter() - t0
        except Exception as e:  # model not available in this fastembed version
            results["methods"][model_name] = {"error": str(e)[:200]}
            print("skip", model_name, e, flush=True)
            continue
        cache: dict[str, np.ndarray] = {}

        def qvec(q):
            if q not in cache:
                cache[q] = np.asarray(next(iter(model.query_embed([q]))))
            return cache[q]

        for variant in ("text", "text+keywords", "enriched"):
            t0 = time.perf_counter()
            mat = np.asarray(list(model.passage_embed([doc_text(c, variant) for c in chunks])))
            mat = mat / np.linalg.norm(mat, axis=1, keepdims=True)
            embed_s = time.perf_counter() - t0

            def cos(q, mat=mat):
                v = qvec(q)
                return mat @ (v / np.linalg.norm(v))

            t0 = time.perf_counter()
            r = evaluate(cos, chunks, cases)
            r.update({"load_s": load_s, "embed_corpus_s": embed_s, "dims": int(mat.shape[1]),
                      "eval_s": time.perf_counter() - t0})
            results["methods"][f"{model_name.split('/')[-1]} | {variant}"] = r

            # Hybrid: reciprocal-rank fusion of BM25 (text+keywords) and this embedding.
            def rrf(q, cos=cos):
                a, b = bm_kw.scores(q), cos(q)
                ra = np.argsort(np.argsort(-a)); rb = np.argsort(np.argsort(-b))
                return 1 / (60 + ra) + 1 / (60 + rb)
            results["methods"][f"hybrid RRF: BM25 + {model_name.split('/')[-1]} | {variant}"] = evaluate(rrf, chunks, cases)
            print("done", model_name, variant, flush=True)

        # Query latency (embedding one new query + scoring 334 chunks).
        t0 = time.perf_counter()
        for i in range(20):
            v = np.asarray(next(iter(model.query_embed([f"latency probe question number {i}"]))))
            _ = mat @ v
        results["methods"][f"{model_name.split('/')[-1]} | text"]["query_ms"] = (time.perf_counter() - t0) / 20 * 1000

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    keys = ["facts (template wording)", "general (official notes)", "probe (user wording)"]
    print("\n| Method | " + " | ".join(f"{k}: no filter / filter" for k in keys) + " | OOS rejected |")
    print("|---|" + "---|" * (len(keys) + 1))
    for m, r in results["methods"].items():
        if "error" in r:
            print(f"| {m} | error: {r['error'][:60]} |")
            continue
        cells = [f"{r[k]['top1_no_filter']:.0%} / {r[k]['top1_scheme_filter']:.0%}" for k in keys]
        print(f"| {m} | " + " | ".join(cells) + f" | {r['out_of_scope']['neg_rejected_at_95pct_recall']:.0%} |")


if __name__ == "__main__":
    main()
