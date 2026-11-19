"""Phase 3 retrieval scoring, shared by the evaluation gate (eval/run.py) and tests.

`decide()` runs a question through what Phase 3 provides: guards -> scheme
resolution -> scheme-filtered search -> confidence threshold. Phase 4 turns the
same decision into a formatted reply.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from bolosip import guards
from bolosip.retriever import Hit, Retriever
from bolosip.schemes import has_fund_signal, resolve

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "eval" / "datasets"


@dataclass
class Decision:
    kind: str                      # answer | clarify | not_found | refusal | performance | privacy
    chunk_id: str | None = None
    score: float | None = None
    scheme_ids: tuple = ()
    hits: list[Hit] = field(default_factory=list)


def decide(r: Retriever, question: str, last_scheme: str | None = None) -> Decision:
    g = guards.check(question)
    if g.kind:
        return Decision(g.kind)
    res = resolve(question, last_scheme)
    if res.kind in ("other_amc", "non_fund", "not_covered"):
        return Decision("not_found")
    if res.kind in ("ambiguous", "multiple"):
        return Decision("clarify", scheme_ids=res.scheme_ids)
    hits = r.search(question, res.scheme_id)
    if not r.is_confident(hits, res.scheme_id):
        return Decision("not_found", hits=hits, score=hits[0].score if hits else None)
    top = hits[0]
    if res.scheme_id is None and top.scheme_id is not None:
        # A scheme-specific fact but no scheme named: ask which one (rule 4), but only if the
        # question reads like a fund question; "what is the money market" is simply not covered.
        if has_fund_signal(question):
            return Decision("clarify", hits=hits, score=top.score)
        return Decision("not_found", hits=hits, score=top.score)
    return Decision("answer", top.chunk["id"], top.score, (res.scheme_id,) if res.scheme_id else (), hits)


def load(name: str) -> list[dict]:
    path = DATASETS / f"{name}.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def gold_id(case: dict) -> str | None:
    """The chunk id a correct answer must come from (official topics: any chunk of that topic)."""
    e = case["expect"]
    return f"{e['scheme_id']}:{e['topic']}" if e.get("scheme_id") else None


def is_correct(r: Retriever, case: dict, d: Decision) -> bool:
    e = case["expect"]
    if e["kind"] == "clarify":
        return d.kind == "clarify" and set(d.scheme_ids) == set(e.get("candidates", d.scheme_ids))
    if e["kind"] != "answer":
        return d.kind == e["kind"] or (e["kind"] == "not_found" and d.kind in ("refusal", "performance", "privacy"))
    if d.kind != "answer":
        return False
    if "topic" not in e:            # resolution-only case: right scheme is enough
        return r.by_id[d.chunk_id]["scheme_id"] == e.get("scheme_id")
    if e.get("scheme_id"):
        return d.chunk_id == gold_id(case)
    return r.by_id[d.chunk_id]["scheme_id"] is None and r.by_id[d.chunk_id]["topic"] == e["topic"]


def reciprocal_rank(r: Retriever, case: dict, k: int = 5) -> float:
    """1 / rank of the right chunk among the top k (scheme filter applied), else 0."""
    e = case["expect"]
    res = resolve(case["question"])
    hits = r.search(case["question"], res.scheme_id if res.kind == "one" else None, k)
    for rank, h in enumerate(hits, 1):
        if (e.get("scheme_id") and h.chunk["id"] == gold_id(case)) or \
           (not e.get("scheme_id") and h.scheme_id is None and h.topic == e["topic"]):
            return 1 / rank
    return 0.0
