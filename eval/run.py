"""Evaluation runner (Doc/eval.md §6).

Phase 0 provides the skeleton: it records run metadata and the Phase 0 gate
checks, and writes a Markdown + JSON report to eval/reports/. Later phases add
datasets (eval/datasets/*.jsonl) and metrics.

Usage:
    python -m eval.run --phase 0
    python -m eval.run --all
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "eval" / "reports"
CURRENT_PHASE = 0


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except Exception:
        return "nogit"


def _corpus_built_on(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("built_on")
    except Exception:
        return None


def phase0_checks() -> list[dict]:
    """Phase 0 gate (Doc/eval.md §5): runner works, config loads without env."""
    results = []

    # Config loads with no environment variables (in a clean subprocess).
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("BOLOSIP_") or k == "GROQ_API_KEY")}
    proc = subprocess.run([sys.executable, "-c", "import bolosip.config"],
                          cwd=ROOT, env=env, capture_output=True, text=True)
    results.append({"check": "Config loads with no environment variables",
                    "pass": proc.returncode == 0,
                    "detail": proc.stderr.strip()[-300:] or "ok"})

    # Unit tests pass.
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                          cwd=ROOT, capture_output=True, text=True)
    last = (proc.stderr.strip().splitlines() or ["no output"])[-1]
    results.append({"check": "Unit tests pass (python -m unittest discover tests)",
                    "pass": proc.returncode == 0, "detail": last})

    # No third-party packages imported by the core package.
    code = ("import sys, bolosip, bolosip.config, bolosip.guards;"
            "std=set(sys.stdlib_module_names);"
            "bad=sorted({m.split('.')[0] for m in sys.modules} - std - {'bolosip'});"
            "print(','.join(bad))")
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    third_party = [m for m in proc.stdout.strip().split(",") if m]
    results.append({"check": "Core imports only the standard library",
                    "pass": proc.returncode == 0 and not third_party,
                    "detail": ", ".join(third_party) or "ok"})
    return results


PHASE_CHECKS = {0: phase0_checks}


def run(phases: list[int]) -> dict:
    from bolosip import config  # imported here so a broken config is reported, not a crash

    s = config.load_settings()
    report = {
        "meta": {
            "date": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "commit": _git_commit(),
            "phases": phases,
            "python": sys.version.split()[0],
            "corpus_built_on": _corpus_built_on(s.corpus_path),
            "llm_mode": s.llm_mode,
            "llm_provider": "groq",
            "model": s.model,
        },
        "checks": [],
        "metrics": [],   # filled from Phase 1 onwards
        "failures": [],
    }
    for ph in phases:
        for r in PHASE_CHECKS.get(ph, lambda: [])():
            report["checks"].append({"phase": ph, **r})
    report["passed"] = all(c["pass"] for c in report["checks"])
    return report


def to_markdown(report: dict) -> str:
    m = report["meta"]
    lines = [
        "# BoloSIP evaluation report",
        "",
        "> Facts-only. No investment advice.",
        "",
        "| Field | Value |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in m.items()],
        "",
        f"**Result: {'PASS' if report['passed'] else 'FAIL'}**",
        "",
        "## Gate checks",
        "",
        "| Phase | Check | Result | Detail |", "|---|---|---|---|",
        *[f"| {c['phase']} | {c['check']} | {'PASS' if c['pass'] else 'FAIL'} | {c['detail']} |"
          for c in report["checks"]],
        "",
        "## Metrics",
        "",
        "No metrics yet (datasets start in Phase 1)." if not report["metrics"] else "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the BoloSIP evaluation.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase", type=int, help="evaluate one phase")
    g.add_argument("--all", action="store_true", help="evaluate every phase up to the current one")
    ap.add_argument("--no-write", action="store_true", help="print the report without saving it")
    args = ap.parse_args(argv)

    if args.phase is not None and not 0 <= args.phase <= 9:
        ap.error("--phase must be between 0 and 9")
    phases = list(range(CURRENT_PHASE + 1)) if args.all else [args.phase]

    report = run(phases)
    md = to_markdown(report)
    print(md)
    if not args.no_write:
        REPORTS.mkdir(parents=True, exist_ok=True)
        stem = f"{dt.date.today().isoformat()}-phase{'-'.join(map(str, phases))}-{report['meta']['commit']}"
        (REPORTS / f"{stem}.md").write_text(md, encoding="utf-8")
        (REPORTS / f"{stem}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"saved eval/reports/{stem}.md")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
