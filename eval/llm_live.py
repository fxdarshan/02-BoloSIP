"""Phase 8 live evaluation with the real Groq model (Doc/eval.md §5, Phase 8 "Live").

    python -m eval.llm_live                 # 135 core facts + 30 paraphrases
    python -m eval.llm_live --limit 10      # a quick look

Needs `pip install groq` and GROQ_API_KEY in .env. It costs quota: about 165 requests and
roughly 60,000 tokens of the 200,000-a-day limit, so it never runs in the default suite.
It paces itself to stay under the per-minute limits (config.GROQ_LIMITS) instead of
falling back, so the fallback rate measures the model, not the rate limit.

Reports (gating marked *): hallucinated numbers in accepted answers*, URLs or advice
words in accepted answers*, fact accuracy with the LLM on vs extractive, fallback rate
and why, finish_reason=length, latency p50/p95, tokens (with reasoning), cost per 100
answers, 429s, and 30 extractive/LLM pairs for the blind helpfulness review.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Groq's list price for openai/gpt-oss-120b in USD per million tokens. Check
# https://groq.com/pricing before quoting a cost; pass --price-in / --price-out to override.
PRICE_IN, PRICE_OUT = 0.15, 0.75


def _load(name: str) -> list[dict]:
    path = ROOT / "eval" / "datasets" / f"{name}.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _value_present(value: str, text: str) -> bool:
    from bolosip.composer import numbers_and_dates
    if value in text:
        return True
    vn, vd = numbers_and_dates(value)
    tn, td = numbers_and_dates(text)
    return bool(vn or vd) and vn <= tn and vd <= td


def main(argv: list[str] | None = None) -> int:
    from bolosip.textutil import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description="Phase 8 live run with Groq")
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions")
    ap.add_argument("--price-in", type=float, default=PRICE_IN)
    ap.add_argument("--price-out", type=float, default=PRICE_OUT)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    from bolosip import composer, config, guards, llm, pipeline
    from bolosip.retriever import Retriever

    base = llm.get_rephraser()
    if base is None:
        print(f"LLM unavailable: {llm.unavailable_reason()}")
        return 2
    r = Retriever()
    by_text = {c["text"]: c for c in r.chunks}

    cases = [c for c in _load("facts") if c.get("ref") == "AC1"]
    cases += [c for c in _load("paraphrases") if c["expect"].get("kind") == "answer"][:30]
    if args.limit:
        cases = cases[: args.limit]

    budget = base.budget
    rows = []

    def paced(question, chunk_text):
        est = llm.estimate_tokens(question, chunk_text)
        while not budget.would_allow(est):           # wait instead of falling back
            time.sleep(1.0)
        raw = base(question, chunk_text)
        rows[-1]["raw"] = raw
        rows[-1]["chunk"] = by_text.get(chunk_text)
        return raw

    start = time.time()
    for i, case in enumerate(cases, 1):
        rows.append({"id": case["id"], "question": case["question"], "expect": case["expect"], "raw": None, "chunk": None})
        before = base.stats.rate_limited
        reply, _ = pipeline.handle(case["question"], {}, retriever=r, rephrase=paced)
        extractive, _ = pipeline.handle(case["question"], {}, retriever=r)
        row = rows[-1]
        row.update(reply=reply, extractive=extractive, limited=base.stats.rate_limited > before)
        row["used_llm"] = reply.text != extractive.text
        if row["raw"] is not None and not row["used_llm"] and row["chunk"]:
            same = " ".join(row["raw"].split()) == " ".join(row["chunk"]["text"].split())
            row["why"] = "model repeated the source" if same else (
                composer.rejection_reason(row["raw"], row["chunk"]) or "prefix/suffix changed")
        if i % 20 == 0:
            print(f"{i}/{len(cases)} done ({time.time() - start:.0f} s)", flush=True)

    st = base.stats
    answers = [x for x in rows if x["reply"].kind == "answer"]
    accepted = [x for x in answers if x["used_llm"]]
    halluc = urls = advice = 0
    for x in accepted:
        src = x["chunk"]["text"] if x["chunk"] else ""
        n, d = composer.numbers_and_dates(x["reply"].text)
        sn, sd = composer.numbers_and_dates(src + " " + x["extractive"].text)
        halluc += not (n <= sn and d <= sd)
        urls += bool(re.search(r"https?://|www\.", x["reply"].text))
        advice += guards.is_advisory(x["reply"].text)

    def accurate(x, which):
        rep = x[which]
        if rep.kind != x["expect"].get("kind"):
            return False
        return all(_value_present(v, rep.text) for v in x["expect"].get("contains", []))

    misses = [x for x in rows if accurate(x, "extractive") and not accurate(x, "reply")]
    acc_llm = sum(accurate(x, "reply") for x in rows)
    acc_ext = sum(accurate(x, "extractive") for x in rows)
    reasons = Counter()
    for x in answers:
        if not x["used_llm"]:
            if x["limited"]:
                reasons["rate limited"] += 1
            elif x["raw"] is None:
                reasons["model gave no usable text (NOT_IN_SOURCE, cut off or error)"] += 1
            else:
                reasons[x.get("why", "?").split(":")[0]] += 1
    lat = sorted(st.latencies_ms) or [0]
    p50, p95 = lat[len(lat) // 2], lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    calls = max(st.calls, 1)
    cost100 = (st.prompt_tokens * args.price_in + st.completion_tokens * args.price_out) / 1e6 / calls * 100
    repeated = sum(1 for x in answers if x.get("why") == "model repeated the source")
    fallback = 1 - (len(accepted) + repeated) / max(len(answers), 1)
    gate = halluc == 0 and urls == 0 and advice == 0 and acc_llm >= acc_ext

    lines = [
        "# BoloSIP Phase 8 live evaluation (Groq)", "", "> Facts-only. No investment advice.", "",
        f"| Field | Value |", "|---|---|",
        f"| Date | {dt.datetime.now().astimezone().isoformat(timespec='seconds')} |",
        f"| Model | {base.model} (reasoning effort {config.LLM_REASONING_EFFORT}, temperature {config.LLM_TEMPERATURE}, max {config.LLM_MAX_COMPLETION_TOKENS} completion tokens) |",
        f"| Retriever | {r.backend_name()} |",
        f"| Questions | {len(rows)} ({sum(1 for x in rows if x['id'].startswith('FACT'))} core facts, {sum(1 for x in rows if not x['id'].startswith('FACT'))} paraphrases) |",
        "", f"**Gate (0 invented numbers, 0 URLs, 0 advice words, accuracy at least extractive): {'PASS' if gate else 'FAIL'}**", "",
        "| Metric | Result |", "|---|---|",
        f"| Hallucinated numbers in accepted answers * | {halluc} |",
        f"| URLs in accepted answers * | {urls} |",
        f"| Advice words in accepted answers * | {advice} |",
        f"| Fact accuracy, LLM on | {acc_llm} / {len(rows)} |",
        f"| Fact accuracy, extractive | {acc_ext} / {len(rows)} |",
        f"| LLM wording used | {len(accepted)} / {len(answers)} answers |",
        f"| Model kept the source wording | {repeated} / {len(answers)} |",
        f"| Fallback rate (rewording rejected or unavailable) | {fallback:.0%} (investigate if > 20%) |",
        f"| Fallback reasons | {', '.join(f'{k}: {v}' for k, v in reasons.most_common()) or 'none'} |",
        f"| Model returned NOT_IN_SOURCE | {st.not_in_source} |",
        f"| Errors / rate-limited (incl. 429) | {st.errors} / {st.rate_limited} |",
        f"| Latency p50 / p95 | {p50:.0f} ms / {p95:.0f} ms (timeout {config.LLM_TIMEOUT_S:.0f} s) |",
        f"| Tokens per call (prompt / completion / of which reasoning) | {st.prompt_tokens / calls:.0f} / {st.completion_tokens / calls:.0f} / {st.reasoning_tokens / calls:.0f} |",
        f"| Tokens in total | {st.prompt_tokens + st.completion_tokens} (daily limit {config.GROQ_LIMITS['tokens_per_day']}) |",
        f"| Cost per 100 answers | ${cost100:.4f} (at ${args.price_in}/M in, ${args.price_out}/M out; check groq.com/pricing) |",
        "", "## Pairs for the blind helpfulness review (first 30 where the LLM wording was used)", "",
        "| ID | Question | Extractive | LLM |", "|---|---|---|---|",
        *[f"| {x['id']} | {x['question']} | {x['extractive'].text} | {x['reply'].text} |" for x in accepted[:30]],
        "", "## Correct with the source text, wrong with the LLM", "",
        "| ID | Expected | LLM answer |", "|---|---|---|",
        *([f"| {x['id']} | {', '.join(x['expect'].get('contains', []))} | {x['reply'].text} |" for x in misses]
          or ["| none | | |"]),
        "", "## Answers that stayed extractive", "",
        "| ID | Question | Model output | Why |", "|---|---|---|---|",
        *[f"| {x['id']} | {x['question']} | {(x['raw'] or '(none)').replace('|', '/')} | {x.get('why') or ('rate limited' if x['limited'] else 'no usable text')} |"
          for x in answers if not x["used_llm"]],
    ]
    md = "\n".join(lines) + "\n"
    print(md)
    if not args.no_write:
        from eval.run import _git_commit
        out = ROOT / "eval" / "reports" / f"{dt.date.today().isoformat()}-phase8-live-{_git_commit()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"saved {out.relative_to(ROOT)}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
