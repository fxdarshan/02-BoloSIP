"""Check task prefixes / instructions for nomic and bge (run in the Python 3.12 research env)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval" / "research"))
import retrieval_benchmark as rb  # noqa: E402

BGE_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def run(model, chunks, cases, variant, doc_prefix="", query_prefix="", use_query_embed=False):
    mat = np.asarray(list(model.embed([doc_prefix + rb.doc_text(c, variant) for c in chunks])))
    mat /= np.linalg.norm(mat, axis=1, keepdims=True)
    cache = {}

    def score(q):
        if q not in cache:
            it = model.query_embed([q]) if use_query_embed else model.embed([query_prefix + q])
            v = np.asarray(next(iter(it)))
            cache[q] = v / np.linalg.norm(v)
        return mat @ cache[q]
    r = rb.evaluate(score, chunks, cases)
    return {"probe": r["probe (user wording)"]["top1_scheme_filter"],
            "facts": r["facts (template wording)"]["top1_scheme_filter"],
            "general": r["general (official notes)"]["top1_scheme_filter"],
            "oos": r["out_of_scope"]["neg_rejected_at_95pct_recall"]}


def main():
    from fastembed import TextEmbedding

    chunks = json.loads((ROOT / "data/corpus.json").read_text(encoding="utf-8"))["chunks"]
    cases = rb.load_cases(chunks)
    out = {}
    nomic = TextEmbedding("nomic-ai/nomic-embed-text-v1.5")
    for variant in ("text+keywords", "enriched"):
        out[f"nomic | {variant} | no prefixes"] = run(nomic, chunks, cases, variant)
        out[f"nomic | {variant} | search_document/search_query"] = run(
            nomic, chunks, cases, variant, "search_document: ", "search_query: ")
        print(variant, "nomic done", flush=True)
    bge = TextEmbedding("BAAI/bge-base-en-v1.5")
    q = "how much does HDFC Mid Cap charge every year"
    a = np.asarray(next(iter(bge.query_embed([q]))))
    b = np.asarray(next(iter(bge.embed([BGE_INSTRUCTION + q]))))
    out["bge query_embed == instruction prefix (cosine)"] = float(a @ b / np.linalg.norm(a) / np.linalg.norm(b))
    for variant in ("text+keywords", "enriched"):
        out[f"bge-base | {variant} | no instruction"] = run(bge, chunks, cases, variant)
        out[f"bge-base | {variant} | query instruction"] = run(bge, chunks, cases, variant, "", BGE_INSTRUCTION)
        print(variant, "bge done", flush=True)
    (ROOT / "eval/research/retrieval_prefix_check.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    for k, v in out.items():
        print(k, v)


if __name__ == "__main__":
    main()
