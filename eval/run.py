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
CURRENT_PHASE = 2


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
    # Compare against the modules already loaded at interpreter start-up: site
    # hooks (e.g. setuptools' _distutils_hack on Python <= 3.11) are not ours.
    code = ("import sys; before=set(sys.modules);"
            "import bolosip, bolosip.config, bolosip.guards;"
            "std=set(sys.stdlib_module_names);"
            "new={m.split('.')[0] for m in set(sys.modules)-before};"
            "bad=sorted(new - std - {'bolosip'});"
            "print(','.join(bad))")
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    third_party = [m for m in proc.stdout.strip().split(",") if m]
    results.append({"check": "Core imports only the standard library",
                    "pass": proc.returncode == 0 and not third_party,
                    "detail": ", ".join(third_party) or "ok"})
    return results


FAILURES: list[dict] = []   # individual failing cases, shown in the report


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "pass": bool(ok), "detail": detail}


def phase1_checks() -> list[dict]:
    """Phase 1 gate (Doc/eval.md §5): corpus complete, correct, and sourced only from the 27 URLs."""
    import re
    from unittest import mock

    sys.path.insert(0, str(ROOT))
    import ingest
    from bolosip import registry
    from bolosip.config import HDFC_FACTSHEET_URL
    from bolosip.textutil import BANNED_JUDGEMENT, RETURN_FIGURE, split_sentences
    from bolosip.topics import SCHEME_TOPICS
    from eval import build_truth

    results = []
    corpus = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
    chunks = {c["id"]: c for c in corpus["chunks"]}
    scheme_chunks = [c for c in corpus["chunks"] if c["scheme_id"]]

    # URL allow-list: registry == problem statement §3.1; corpus cites nothing else.
    ps = (ROOT / "Doc" / "problem_statement.md").read_text(encoding="utf-8")
    ps_urls = set(re.findall(r"https://groww\.in/mutual-funds/[a-z0-9-]+", ps.split("### 3.1", 1)[1].split("### 3.2", 1)[0]))
    src_urls = {v["url"] for v in corpus.get("sources", {}).values()}
    stray = sorted({c["source_url"] for c in scheme_chunks} - set(registry.ALLOWED_URLS) - {HDFC_FACTSHEET_URL})
    ok = ps_urls == set(registry.ALLOWED_URLS) == src_urls and not stray and len(ps_urls) == 27
    results.append(_check("URL allow-list: exactly the 27 problem-statement URLs, nothing else",
                          ok, f"{len(src_urls)} fetched; stray sources: {stray or 'none'}"))

    # Coverage.
    schemes = {c["scheme_id"] for c in scheme_chunks}
    results.append(_check("Scheme coverage", len(schemes) == 27, f"{len(schemes)} / 27"))
    pairs = {(c["scheme_id"], c["topic"]) for c in scheme_chunks}
    results.append(_check("Topic coverage (12 per scheme)", len(pairs) == 27 * len(SCHEME_TOPICS),
                          f"{len(pairs)} / {27 * len(SCHEME_TOPICS)}"))

    # Dataset is in sync with the saved pages.
    fresh = build_truth.build()
    stored = build_truth.load() if build_truth.DATASET.exists() else []
    results.append(_check("facts.jsonl matches the saved pages (run python -m eval.build_truth if not)",
                          fresh == stored, f"{len(stored)} cases stored, {len(fresh)} expected"))

    # Fact agreement: corpus chunk vs independent truth.
    def agree(case: dict) -> bool:
        e = case["expect"]
        c = chunks.get(f"{e['scheme_id']}:{e['topic']}")
        if not c:
            return False
        text = c["text"].casefold()
        return all(v.casefold() in text for v in e["contains"]) and c["source_url"] == e["source_url"]

    for ref, label, threshold in (("AC1", "Core fact agreement (135 checks, AC 1)", 1.0),
                                  ("AC1-extended", "Extended fact agreement (189 checks)", 0.98)):
        cases = [c for c in fresh if c["ref"] == ref]
        bad = [c for c in cases if not agree(c)]
        for c in bad:
            got = chunks.get(f"{c['expect']['scheme_id']}:{c['expect']['topic']}", {}).get("text", "(missing)")
            FAILURES.append({"id": c["id"], "expected": c["expect"]["contains"], "got": got})
        rate = 1 - len(bad) / len(cases) if cases else 0
        results.append(_check(label, rate >= threshold,
                              f"{len(cases) - len(bad)} / {len(cases)} ({rate:.1%}; need ≥ {threshold:.0%})"))

    # Riskometer cross-check on every saved page (GAP-03).
    mismatched = []
    for s in registry.SCHEMES:
        d = build_truth.page_data(ingest.RAW / f"{s.id}.html")
        code = str(d["scheme_code"])
        own = next(x["risk"] for x in d["return_stats"] if str(x.get("scheme_code")) == code)
        m = re.search(r"Risk is ([A-Za-z ]+?)\.?\s*$", d.get("meta_desc") or "")
        if not m or m.group(1).strip().lower() != own.lower():
            mismatched.append(s.id)
    results.append(_check("Riskometer: data value agrees with page summary", not mismatched,
                          f"{27 - len(mismatched)} / 27 agree" + (f"; {mismatched}" if mismatched else "")))

    # Format and content rules.
    over = [c["id"] for c in corpus["chunks"] if not 1 <= len(split_sentences(c["text"])) <= 3]
    results.append(_check("Every chunk has 1–3 sentences", not over, f"{len(over)} over the limit"))
    figs = [c["id"] for c in corpus["chunks"] if RETURN_FIGURE.search(c["text"])]
    results.append(_check("No return / performance figures", not figs, f"{len(figs)} found"))
    words = [c["id"] for c in corpus["chunks"] if BANNED_JUDGEMENT.search(c["text"])]
    results.append(_check("No judgement words (CMP-01)", not words, f"{len(words)} found"))
    results.append(_check("Corpus passes ingest validation", not ingest.validate_corpus(corpus),
                          f"{len(ingest.validate_corpus(corpus))} problems"))

    # Atomic write (GAP-04) and fetch resilience, via the real code paths.
    proc = subprocess.run([sys.executable, "-m", "unittest", "-q", "tests.test_ingest.TestAtomicWriteAndLock"],
                          cwd=ROOT, capture_output=True, text=True)
    results.append(_check("Atomic write keeps old corpus on failure; lock works", proc.returncode == 0,
                          (proc.stderr.strip().splitlines() or ["?"])[-1]))
    with mock.patch.object(ingest, "fetch", side_effect=OSError("network down")):
        try:
            built, _, _ = ingest.build(offline=False, log=lambda *a: None)
            origins = {v["origin"] for v in built["sources"].values()}
            ok, detail = origins == {"snapshot"}, f"network off → {len(built['sources'])} schemes from snapshots"
        except ingest.IngestError as e:
            ok, detail = False, str(e)[:200]
    results.append(_check("Fetch resilience: network failure falls back to snapshots", ok, detail))

    # Manual live spot check recorded in eval/manual/phase1_spotcheck.json.
    manual = ROOT / "eval" / "manual" / "phase1_spotcheck.json"
    if manual.exists():
        items = json.loads(manual.read_text(encoding="utf-8"))["checks"]
        good = sum(1 for i in items if i.get("match"))
        results.append(_check("Live spot check: 10 facts compared with live pages by hand",
                              len(items) >= 10 and good == len(items), f"{good} / {len(items)} match"))
    else:
        results.append(_check("Live spot check: 10 facts compared with live pages by hand", False,
                              "eval/manual/phase1_spotcheck.json missing"))
    return results


SECTIONS: list[str] = []    # extra Markdown sections (e.g. confusion matrices)


def _load_set(name: str) -> list[dict]:
    path = ROOT / "eval" / "datasets" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def phase2_checks() -> list[dict]:
    """Phase 2 gate (Doc/eval.md §5): the three guards on their own, no retrieval."""
    sys.path.insert(0, str(ROOT))
    from bolosip import guards

    advice, perf, pii, facts = (_load_set(n) for n in ("advice", "performance", "pii", "facts"))
    results = []

    def rate(cases, predicate):
        hits = [c for c in cases if predicate(c)]
        return len(hits), len(cases)

    def gate(name, cases, predicate, *, minimum=None, maximum=None, record_misses=True):
        n, total = rate(cases, predicate)
        value = n / total if total else 0.0
        ok = (minimum is None or value >= minimum) and (maximum is None or value <= maximum)
        bound = f"need ≥ {minimum:.0%}" if minimum is not None else f"max {maximum:.0%}"
        results.append(_check(name, ok, f"{n} / {total} ({value:.1%}; {bound})"))
        if record_misses and not ok:
            for c in cases:
                if (predicate(c) if maximum is not None else not predicate(c)):
                    FAILURES.append({"id": c["id"], "expected": [str(c.get("expect", {}).get("kind"))],
                                     "got": f"{guards.check(c['question']).kind}: {c['question']}"})

    kind = lambda c: guards.check(c["question"]).kind  # noqa: E731
    pii_pos = [c for c in pii if c["expect"]["kind"] == "privacy"]
    pii_neg = [c for c in pii if c["expect"]["kind"] is None]
    adv_pos = [c for c in advice if c["expect"]["kind"] == "refusal"]
    adv_neg = [c for c in advice if c["expect"]["kind"] is None]
    prf_pos = [c for c in perf if c["expect"]["kind"] == "performance"]
    prf_neg = [c for c in perf if c["expect"]["kind"] is None]

    gate("PII recall (personal data caught)", pii_pos, lambda c: bool(guards.find_pii(c["question"])), minimum=1.0)
    gate("PII false positives (look-alikes and fact questions)", pii_neg + facts,
         lambda c: bool(guards.find_pii(c["question"])), maximum=0.02)
    leaks = [(c["id"], v) for c in pii_pos for v in c["expect"].get("values", [])
             if v.lower() in guards.redact(c["question"]).lower()]
    results.append(_check("Redaction leaves no personal-data value (hard gate)", not leaks,
                          f"{len(leaks)} values survived" + (f": {[i for i, _ in leaks]}" if leaks else "")))
    gate("Refusal recall (advice refused, AC 4)", adv_pos, lambda c: kind(c) == "refusal", minimum=1.0)
    gate("False refusals (fact questions refused)", facts + adv_neg + prf_neg,
         lambda c: guards.is_advisory(c["question"]), maximum=0.03)
    gate("Performance recall (returns → factsheet, AC 5)", prf_pos, lambda c: kind(c) == "performance", minimum=0.97)
    gate("Performance false positives", facts + prf_neg, lambda c: guards.is_performance(c["question"]),
         maximum=0.02)
    order = [c for c in pii + advice if c["ref"] == "rule-order" or c["id"].startswith("ADV-24")]
    gate("Rule order: privacy → advice → performance", order, lambda c: kind(c) == c["expect"]["kind"],
         minimum=1.0)

    corpus = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
    flagged = [c["id"] for c in corpus["chunks"] if guards.find_pii(c["text"]) or guards.is_advisory(c["text"])]
    results.append(_check("No stored fact trips a guard (needed for Phase 7 output checks)", not flagged,
                          f"{len(flagged)} flagged" + (f": {flagged[:5]}" if flagged else "")))

    proc = subprocess.run([sys.executable, "-m", "unittest", "-q", "tests.test_guards.TestSpeed"],
                          cwd=ROOT, capture_output=True, text=True)
    results.append(_check("Regex speed: every pattern < 5 ms on 500-character worst cases", proc.returncode == 0,
                          (proc.stderr.strip().splitlines() or ["?"])[-1]))

    # Confusion matrix over every guard case: expected kind (rows) vs actual (columns).
    labels = ["privacy", "refusal", "performance", None]
    grid = {(e, a): 0 for e in labels for a in labels}
    for c in pii + advice + perf:
        grid[(c["expect"]["kind"], kind(c))] += 1
    name = lambda k: k or "none"  # noqa: E731
    SECTIONS.append("\n".join([
        "## Phase 2 confusion matrix (expected rows × actual columns)", "",
        "| expected \\ actual | " + " | ".join(name(a) for a in labels) + " |",
        "|---|" + "---|" * len(labels),
        *[f"| {name(e)} | " + " | ".join(str(grid[(e, a)]) for a in labels) + " |" for e in labels],
        "", f"{len(pii) + len(advice) + len(perf)} guard cases; {len(facts)} fact questions also checked for "
            "false positives.",
    ]))
    return results


PHASE_CHECKS = {0: phase0_checks, 1: phase1_checks, 2: phase2_checks}


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
        "failures": [],
    }
    for ph in phases:
        for r in PHASE_CHECKS.get(ph, lambda: [])():
            report["checks"].append({"phase": ph, **r})
    report["failures"] = FAILURES
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
        "## Failing cases",
        "",
        *(["None."] if not report["failures"] else
          ["| ID | Expected to contain | Got |", "|---|---|---|",
           *[f"| {f['id']} | {', '.join(f['expected'])} | {f['got']} |" for f in report["failures"]]]),
        *(["", *SECTIONS] if SECTIONS else []),
    ]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the BoloSIP evaluation.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--phase", type=int, help="evaluate one phase")
    g.add_argument("--all", action="store_true", help="evaluate every phase up to the current one")
    ap.add_argument("--no-write", action="store_true", help="print the report without saving it")
    args = ap.parse_args(argv)
    from bolosip.textutil import utf8_output
    utf8_output()

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
