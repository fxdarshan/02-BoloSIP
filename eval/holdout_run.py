"""One-off run of a held-out set through the full pipeline (no tuning afterwards).

    .venv/Scripts/python.exe -m eval.holdout_run holdout2

Prints every case and the score per kind, and writes eval/reports/<date>-<set>.md.
Held-out sets are run once, after the system is frozen, to check whether tuning on the
other sets overfitted (Doc/eval.md). Fixing what they reveal is fine; re-running the same
set to tune against it is not.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    from bolosip import pipeline
    from bolosip.retriever import Retriever
    from bolosip.textutil import utf8_output
    from eval.answer_eval import check_reply
    utf8_output()
    name = (argv or sys.argv[1:] or ["holdout2"])[0]
    cases = [json.loads(l) for l in (ROOT / "eval" / "datasets" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    r = Retriever()
    ok, by_kind, rows = 0, Counter(), []
    for c in cases:
        reply, _ = pipeline.handle(c["question"], {}, retriever=r)
        problems = check_reply(r, reply, c["expect"])
        good = not problems
        ok += good
        by_kind[(c["expect"]["kind"], good)] += 1
        rows.append((c["id"], c["question"], c["expect"]["kind"], reply.kind, good, "; ".join(problems), reply.text))
    kinds = sorted({k for k, _ in by_kind})
    lines = [f"# Held-out run: {name}", "", "> Facts-only. No investment advice.", "",
             f"Date: {dt.date.today().isoformat()} · retriever: {r.backend_name()} · cases: {len(cases)}", "",
             f"**Correct: {ok} / {len(cases)} ({ok / len(cases):.1%})**", "",
             "| Expected kind | Correct | Total |", "|---|---|---|",
             *[f"| {k} | {by_kind[(k, True)]} | {by_kind[(k, True)] + by_kind[(k, False)]} |" for k in kinds],
             "", "## Misses", "", "| ID | Question | Expected | Got | Problem | Reply |", "|---|---|---|---|---|---|",
             *([f"| {i} | {q} | {e} | {g} | {p} | {t[:120]} |" for i, q, e, g, good, p, t in rows if not good] or ["| none | | | | | |"])]
    md = "\n".join(lines) + "\n"
    print(md)
    out = ROOT / "eval" / "reports" / f"{dt.date.today().isoformat()}-{name}.md"
    out.write_text(md, encoding="utf-8")
    print(f"saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
