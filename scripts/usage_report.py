"""Usage report from the thread database: what BoloSIP answers and where it falls short.

    python scripts/usage_report.py                      # data/bolosip.sqlite3 (BOLOSIP_DB)
    python scripts/usage_report.py --db data/preview.sqlite3
    python scripts/usage_report.py --show-unanswered    # also list the questions answered "not found"

Conversation analytics in the sense of the chatbot-flow-design skill: reply mix per kind
(the "fallback rate"), answers per topic and per scheme, and threads that hit "not found"
twice in a row. Read-only and local: it prints counts, and prints question text only with
--show-unanswered (stored questions are already redacted, see bolosip/store.py).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bolosip import config, registry  # noqa: E402
from bolosip.textutil import utf8_output  # noqa: E402

KIND_ORDER = ("answer", "clarify", "not_found", "refusal", "performance", "privacy", "help")


def topic_of(text: str, chunks: list[dict]) -> str | None:
    """The topic of an extractive answer: the chunk whose text it contains."""
    for c in chunks:
        if c["text"] in text:
            return c["topic"]
    return None


def report(db: Path, show_unanswered: bool = False, out=print) -> dict:
    if not db.exists():
        out(f"No database at {db}. Start the server and ask something first.")
        return {}
    chunks = json.loads(config.SETTINGS.corpus_path.read_text(encoding="utf-8"))["chunks"]
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        threads = con.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        rows = con.execute("SELECT thread_id, role, text, kind, scheme_id FROM messages ORDER BY thread_id, id").fetchall()
        has_fb = "feedback" in {r[1] for r in con.execute("PRAGMA table_info(messages)")}
        rated = con.execute(
            "SELECT a.feedback, (SELECT u.text FROM messages u WHERE u.thread_id = a.thread_id AND u.role = 'user' "
            "AND u.id < a.id ORDER BY u.id DESC LIMIT 1), a.text FROM messages a "
            "WHERE a.role = 'assistant' AND a.feedback IS NOT NULL").fetchall() if has_fb else []
    finally:
        con.close()

    replies = [r for r in rows if r[1] == "assistant"]
    kinds = Counter(r[3] for r in replies)
    total = len(replies)
    topics = Counter(topic_of(r[2], chunks) or "?" for r in replies if r[3] == "answer")
    schemes = Counter(r[4] for r in replies if r[3] == "answer" and r[4])

    # Questions answered "not found", and threads with two "not found" replies in a row.
    unanswered, repeat_threads, last_q, prev = [], set(), {}, {}
    for thread_id, role, text, kind, _ in rows:
        if role == "user":
            last_q[thread_id] = text
            continue
        if kind == "not_found":
            unanswered.append(last_q.get(thread_id, ""))
            if prev.get(thread_id) == "not_found":
                repeat_threads.add(thread_id)
        prev[thread_id] = kind

    out(f"BoloSIP usage report ({db})")
    out(f"Threads: {threads}   Replies: {total}")
    if not total:
        return {"threads": threads, "replies": 0}
    out("\nReplies by kind")
    for k in KIND_ORDER:
        if kinds[k]:
            out(f"  {k:<12} {kinds[k]:>6}  {kinds[k] / total:6.1%}")
    fallback = kinds["not_found"] + kinds["clarify"]
    out(f"\nFallback rate (not found + clarify): {fallback / total:.1%}   "
        f"(above 25-30% means questions people ask are missing)")
    out(f"Threads with two 'not found' in a row: {len(repeat_threads)} of {threads}")
    out("\nAnswers by topic")
    for t, n in topics.most_common():
        out(f"  {t:<22} {n:>6}")
    out("\nAnswers by scheme (top 10)")
    names = {s.id: s.name for s in registry.SCHEMES}
    for s, n in schemes.most_common(10):
        out(f"  {names.get(s, s):<40} {n:>6}")
    up = sum(1 for r in rated if r[0] > 0)
    down = [r for r in rated if r[0] < 0]
    out(f"\nFeedback: {up} helpful, {len(down)} not helpful")
    if show_unanswered and down:
        out("\nAnswers marked 'not helpful' (question stored redacted)")
        for _, q, a in down[:30]:
            out(f"  Q: {q}\n     A: {a[:140]}")
    if show_unanswered and unanswered:
        out("\nQuestions answered 'not found' (stored redacted), most frequent first")
        for q, n in Counter(unanswered).most_common(30):
            out(f"  {n:>3} × {q}")
    return {"threads": threads, "replies": total, "kinds": dict(kinds), "fallback_rate": fallback / total,
            "repeat_not_found_threads": len(repeat_threads), "topics": dict(topics),
            "feedback": {"helpful": up, "not_helpful": len(down)}}


def main(argv: list[str] | None = None) -> int:
    utf8_output()
    ap = argparse.ArgumentParser(description="BoloSIP usage report (local, read-only).")
    ap.add_argument("--db", type=Path, default=config.SETTINGS.db_path, help="thread database (default: BOLOSIP_DB)")
    ap.add_argument("--show-unanswered", action="store_true", help="list questions that got 'not found'")
    args = ap.parse_args(argv)
    db = args.db if args.db.is_absolute() else ROOT / args.db
    report(db, args.show_unanswered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
