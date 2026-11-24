"""Command line (milestone M1): ask BoloSIP from the terminal.

    python -m bolosip "What is the expense ratio of HDFC Mid Cap Fund?"
    python -m bolosip "HDFC Mid Cap exit load" "what about its benchmark?"   # one thread
    python -m bolosip --json "ELSS lock-in period"
    python -m bolosip                                                     # interactive

Several questions on one command line share a thread, so follow-ups work. Nothing is
stored: threads and storage arrive with the server in Phase 5.
"""
from __future__ import annotations

import argparse
import json
import sys

from bolosip import config, llm, pipeline
from bolosip.textutil import utf8_output


def main(argv: list[str] | None = None) -> int:
    utf8_output()
    ap = argparse.ArgumentParser(prog="python -m bolosip", description=config.DISCLAIMER)
    ap.add_argument("questions", nargs="*", help="one or more questions, asked in order in one thread")
    ap.add_argument("--json", action="store_true", help="print each reply as JSON")
    args = ap.parse_args(argv)

    ctx: dict = {}

    def ask(q: str) -> None:
        nonlocal ctx
        reply, ctx = pipeline.handle(q, ctx, rephrase=llm.get_rephraser())
        if args.json:
            print(json.dumps(reply.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"> {q}\n{reply.render()}\n")

    if args.questions:
        for q in args.questions:
            ask(q)
        return 0

    print(f"BoloSIP. {config.DISCLAIMER}\nAsk a question (empty line or Ctrl+C to quit).\n")
    try:
        while True:
            q = input("> ").strip()
            if not q:
                return 0
            reply, ctx = pipeline.handle(q, ctx, rephrase=llm.get_rephraser())
            print(reply.render() + "\n")
    except (EOFError, KeyboardInterrupt):
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
