"""Follow-up to retrieval_benchmark.py: failures, model size/speed, quantised model, nomic prefixes.

Run in the same Python 3.12 research env as retrieval_benchmark.py.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval" / "research"))
import retrieval_benchmark as rb  # noqa: E402


def dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def main():
    from fastembed import TextEmbedding

    chunks = json.loads((ROOT / "data/corpus.json").read_text(encoding="utf-8"))["chunks"]
    cases = rb.load_cases(chunks)
    ids = [(c["scheme_id"], c["topic"]) for c in chunks]
    official = np.array([c["scheme_id"] is None for c in chunks])
    report = {}

    candidates = [("nomic-ai/nomic-embed-text-v1.5", "text+keywords"),
                  ("nomic-ai/nomic-embed-text-v1.5-Q", "text+keywords"),
                  ("BAAI/bge-base-en-v1.5", "enriched"),
                  ("BAAI/bge-small-en-v1.5", "enriched")]
    for name, variant in candidates:
        t0 = time.perf_counter()
        try:
            model = TextEmbedding(model_name=name)
        except Exception as e:
            report[name] = {"error": str(e)[:200]}
            continue
        load_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        mat = np.asarray(list(model.passage_embed([rb.doc_text(c, variant) for c in chunks])))
        mat /= np.linalg.norm(mat, axis=1, keepdims=True)
        embed_s = time.perf_counter() - t0
        qcache = {}

        def score(q):
            if q not in qcache:
                v = np.asarray(next(iter(model.query_embed([q]))))
                qcache[q] = v / np.linalg.norm(v)
            return mat @ qcache[q]

        r = rb.evaluate(score, chunks, cases)
        fails = []
        for case in cases["probe (user wording)"]:
            s = score(case["q"])
            mask = official | np.array([c["scheme_id"] == case["scheme"] for c in chunks]) if case["scheme"] else None
            s2 = np.where(mask, s, -np.inf) if mask is not None else s
            got = ids[int(np.argmax(s2))]
            if got != (case["scheme"], case["topic"]):
                fails.append({"q": case["q"], "expected": case["topic"], "got": got[1]})
        t0 = time.perf_counter()
        for i in range(30):
            v = np.asarray(next(iter(model.query_embed([f"what is the exit load of fund number {i}"]))))
            _ = mat @ v
        q_ms = (time.perf_counter() - t0) / 30 * 1000
        cache_dir = Path(model.model._model_dir) if hasattr(model.model, "_model_dir") else None
        report[f"{name} | {variant}"] = {
            "probe_filter": r["probe (user wording)"]["top1_scheme_filter"],
            "facts_filter": r["facts (template wording)"]["top1_scheme_filter"],
            "general": r["general (official notes)"]["top1_scheme_filter"],
            "oos_rejected": r["out_of_scope"]["neg_rejected_at_95pct_recall"],
            "load_s": round(load_s, 2), "embed_corpus_s": round(embed_s, 2), "query_ms": round(q_ms, 1),
            "dims": int(mat.shape[1]), "model_mb": round(dir_size_mb(cache_dir), 1) if cache_dir else None,
            "probe_failures": fails,
        }
        print(name, variant, {k: v for k, v in report[f"{name} | {variant}"].items() if k != "probe_failures"},
              flush=True)

    # Does fastembed apply nomic's required task prefixes?
    from fastembed import TextEmbedding as TE
    m = TE(model_name="nomic-ai/nomic-embed-text-v1.5")
    q = "how much does HDFC Mid Cap charge every year"
    a = np.asarray(next(iter(m.query_embed([q]))))
    b = np.asarray(next(iter(m.embed([q]))))
    c = np.asarray(next(iter(m.embed(["search_query: " + q]))))
    cos = lambda x, y: float(x @ y / np.linalg.norm(x) / np.linalg.norm(y))  # noqa: E731
    report["nomic_prefix_check"] = {"query_embed_vs_plain": cos(a, b), "query_embed_vs_search_query_prefix": cos(a, c)}
    print("nomic prefix check", report["nomic_prefix_check"])
    (ROOT / "eval/research/retrieval_followup.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
