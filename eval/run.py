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
import io
import json
import re
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "eval" / "reports"
CURRENT_PHASE = 6


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
    # Name the failing tests (and their assertion), so a failure seen only in CI can be traced.
    failing = re.findall(r"^(?:FAIL|ERROR): (\S+) \((\S+)\)", proc.stderr, re.M)
    reasons = re.findall(r"^(\w+(?:Error|Exception)\b.*)$", proc.stderr, re.M)
    if failing:
        last += "; " + ", ".join(cls if cls.endswith(name) else f"{cls}.{name}" for name, cls in failing)
        if reasons:
            last += f" ({reasons[0][:160]})"
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
    # "low" (eval.md §5) is allowed only as a quoted SEBI riskometer level, inside the official list of
    # levels, or as AMFI's factual "lower expense ratio" for Direct plans; anywhere else it's judgement.
    allowed_low = re.compile(r'"Low(?: to Moderate)?"|Low, Low to Moderate|Direct Plan has a lower expense ratio')
    lows = [c["id"] for c in corpus["chunks"]
            if re.search(r"\blow(?:er|est)?\b", allowed_low.sub(" ", c["text"]), re.IGNORECASE)]
    results.append(_check("No judgement words (CMP-01), incl. 'low' outside SEBI levels",
                          not words and not lows, f"{len(words) + len(lows)} found"
                          + (f": {(words + lows)[:5]}" if words or lows else "")))
    results.append(_check("Corpus passes ingest validation", not ingest.validate_corpus(corpus),
                          f"{len(ingest.validate_corpus(corpus))} problems"))

    # Atomic write (GAP-04) and fetch resilience, via the real code paths.
    proc = subprocess.run([sys.executable, "-m", "unittest", "-q", "tests.test_ingest.TestAtomicWriteAndLock"],
                          cwd=ROOT, capture_output=True, text=True)
    results.append(_check("Atomic write keeps old corpus on failure; lock works", proc.returncode == 0,
                          (proc.stderr.strip().splitlines() or ["?"])[-1]))
    # Fetch resilience (eval.md §5): network off -> exit 1, snapshots used, footer dates = recorded fetch dates.
    import tempfile
    fetch_log = json.loads((ingest.RAW / "fetched.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with mock.patch.object(ingest, "fetch", side_effect=OSError("network down")), \
             mock.patch.object(ingest, "CORPUS", tmp / "corpus.json"), \
             mock.patch.object(ingest, "LOCK", tmp / ".ingest.lock"), \
             mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            code = ingest.main(["--no-embed"])
        built = json.loads((tmp / "corpus.json").read_text(encoding="utf-8")) if (tmp / "corpus.json").exists() else {}
    origins = {v["origin"] for v in built.get("sources", {}).values()}
    dishonest = [c["id"] for c in built.get("chunks", [])
                 if c["scheme_id"] and c["source_url"] != HDFC_FACTSHEET_URL
                 and c["as_of"] != fetch_log.get(c["scheme_id"], {}).get("fetched_on")]
    ok = code == 1 and origins == {"snapshot"} and not dishonest
    results.append(_check("Fetch resilience: network off → exit 1, snapshots used, dates honest", ok,
                          f"exit {code}; {len(built.get('sources', {}))} from snapshots; "
                          f"{len(dishonest)} chunks with a wrong date"))

    # Per-scheme table (eval.md §5: "Report adds a per-scheme table").
    rows = []
    for s in registry.SCHEMES:
        topics = {c["topic"] for c in scheme_chunks if c["scheme_id"] == s.id}
        cases = [c for c in fresh if c["expect"]["scheme_id"] == s.id]
        bad_ids = [c["expect"]["topic"] for c in cases if not agree(c)]
        src = corpus["sources"].get(s.id, {})
        rows.append(f"| {s.id} | {len(topics)} / {len(SCHEME_TOPICS)} | {len(cases)} | "
                    f"{', '.join(bad_ids) or '0'} | {src.get('origin', '?')}, {src.get('fetched_on', '?')} |")
    SECTIONS.append("\n".join([
        "## Phase 1 per-scheme table", "",
        "| Scheme | Topics present | Values checked | Mismatches | Source |", "|---|---|---|---|---|", *rows]))

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

    advice, perf, pii, facts, general = (_load_set(n) for n in ("advice", "performance", "pii", "facts", "general"))
    results = []
    misses: list[str] = []      # every miss and false positive, always listed (eval.md §5)

    def rate(cases, predicate):
        hits = [c for c in cases if predicate(c)]
        return len(hits), len(cases)

    def gate(name, cases, predicate, *, minimum=None, maximum=None, record_misses=True):
        n, total = rate(cases, predicate)
        value = n / total if total else 0.0
        ok = (minimum is None or value >= minimum) and (maximum is None or value <= maximum)
        bound = f"need ≥ {minimum:.0%}" if minimum is not None else f"max {maximum:.0%}"
        results.append(_check(name, ok, f"{n} / {total} ({value:.1%}; {bound})"))
        for c in cases:
            wrong = predicate(c) if maximum is not None else not predicate(c)
            if wrong:
                misses.append(f"| {name} | {c['id']} | {c.get('expect', {}).get('kind')} | "
                              f"{guards.check(c['question']).kind} | {c['question']} |")
                if record_misses and not ok:
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
    gate("PII false positives (look-alikes and fact questions)", pii_neg + facts + general,
         lambda c: bool(guards.find_pii(c["question"])), maximum=0.02)
    leaks = [(c["id"], v) for c in pii_pos for v in c["expect"].get("values", [])
             if v.lower() in guards.redact(c["question"]).lower()]
    results.append(_check("Redaction leaves no personal-data value (hard gate)", not leaks,
                          f"{len(leaks)} values survived" + (f": {[i for i, _ in leaks]}" if leaks else "")))
    gate("Refusal recall (advice refused, AC 4)", adv_pos, lambda c: kind(c) == "refusal", minimum=1.0)
    gate("False refusals (fact + general questions refused)", facts + general + adv_neg + prf_neg,
         lambda c: guards.is_advisory(c["question"]), maximum=0.03)
    gate("Performance recall (returns → factsheet, AC 5)", prf_pos, lambda c: kind(c) == "performance", minimum=0.97)
    gate("Performance false positives (fact + general questions)", facts + general + prf_neg,
         lambda c: guards.is_performance(c["question"]), maximum=0.02)
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
        "", f"{len(pii) + len(advice) + len(perf)} guard cases; {len(facts)} fact and {len(general)} general "
            "questions also checked for false positives.",
        "", "### Every miss and false positive, by ID", "",
        *(["None."] if not misses else
          ["| Gate | ID | Expected | Got | Question |", "|---|---|---|---|---|", *misses]),
    ]))
    return results


def phase3_checks() -> list[dict]:
    """Phase 3 gate (Doc/eval.md §5, plan Phase 3 exit criteria): resolution and retrieval."""
    import time
    from collections import defaultdict

    sys.path.insert(0, str(ROOT))
    from bolosip import registry
    from bolosip.retriever import Retriever
    from bolosip.schemes import resolve
    from eval.retrieval_eval import decide, gold_id, is_correct, reciprocal_rank

    results = []
    try:
        r = Retriever()
    except RuntimeError as e:          # BOLOSIP_RETRIEVER=embed but embeddings unavailable
        return [_check("Retriever starts", False, str(e)[:200])]
    dense = r.store is not None
    results.append(_check("Retriever starts (backend in use)", True,
                          r.backend_name() + (f" — {r.reason}" if r.reason else "")))

    facts = [{"id": c["id"], "question": c["question"], "expect": {"kind": "answer", **{
        k: c["expect"][k] for k in ("scheme_id", "topic")}}} for c in _load_set("facts")]
    general = [{"id": c["id"], "question": c["question"],
                "expect": {"kind": "answer", "scheme_id": None, "topic": c["expect"]["topic"]}}
               for c in _load_set("general")]
    paraphrases, ambiguous, ooc, holdout = (_load_set(n) for n in ("paraphrases", "ambiguous", "out_of_corpus",
                                                                    "holdout"))
    hold_pos = [c for c in holdout if c["expect"]["kind"] == "answer"]
    hold_neg = [c for c in holdout if c["expect"]["kind"] != "answer"]
    decisions = {}

    def d(c):
        if c["question"] not in decisions:
            decisions[c["question"]] = decide(r, c["question"])
        return decisions[c["question"]]

    misses: list[str] = []

    def accuracy(name, cases, threshold, *, dense_only=False):
        if dense_only and not dense:
            results.append(_check(name, True, "skipped: dense backend not available here (BM25 fallback); "
                                              "required in the Python 3.12 embed CI job"))
            return
        bad = [c for c in cases if not is_correct(r, c, d(c))]
        for c in bad:
            res = resolve(c["question"])
            top5 = r.search(c["question"], res.scheme_id if res.kind == "one" else None)
            misses.append(f"| {name.split(' (')[0]} | {c.get('id', '')} | {c['question']} | "
                          f"{c['expect'].get('topic') or c['expect']['kind']} | {d(c).kind} {d(c).chunk_id or ''} | "
                          + ", ".join(f"{h.chunk['id']} {h.score:.2f}" for h in top5) + " |")
        rate = 1 - len(bad) / len(cases)
        results.append(_check(name, rate >= threshold,
                              f"{len(cases) - len(bad)} / {len(cases)} ({rate:.1%}; need ≥ {threshold:.0%})"))

    # Scheme resolution (no retrieval involved).
    res_cases = [(c["question"], c["expect"]["scheme_id"]) for c in facts] + \
                [(c["question"], c["expect"]["scheme_id"]) for c in ambiguous if c["expect"]["kind"] == "answer"]
    ok = sum(resolve(q).scheme_ids == (sid,) for q, sid in res_cases)
    results.append(_check("Scheme resolution accuracy", ok / len(res_cases) >= 0.99,
                          f"{ok} / {len(res_cases)} ({ok / len(res_cases):.1%}; need ≥ 99%)"))
    accuracy("Clarify accuracy (confusable names, AC 7a)",
             [c for c in ambiguous if c["expect"]["kind"] == "clarify"], 1.0)
    accuracy("Other fund houses / non-fund HDFC / schemes not covered → not found (GAP-01)",
             [c for c in ambiguous + ooc if c["expect"].get("reason") in
              ("other_amc", "non_fund", "scheme_not_covered")], 1.0)

    # Retrieval accuracy through the full Phase 3 decision.
    accuracy("Top-1 on template-wording facts (324)", facts, 0.98)
    accuracy("Top-1 on general questions", general, 0.90, dense_only=True)
    accuracy("Top-1 on paraphrases (user wording)", paraphrases, 0.90, dense_only=True)
    accuracy("Top-1 on the held-out set (never tuned on)", hold_pos, 0.90, dense_only=True)
    mrr_cases = facts + general + paraphrases
    mrr = sum(reciprocal_rank(r, c) for c in mrr_cases) / len(mrr_cases)
    results.append(_check("MRR@5 (facts + general + paraphrases)", mrr >= 0.95 or not dense,
                          f"{mrr:.3f} (need ≥ 0.95" + ("" if dense else "; BM25 reported only") + ")"))

    # Out of scope: never answered with a fact (hard gate); mostly an explicit not-found.
    oos = ooc + hold_neg
    answered = [c for c in oos if d(c).kind == "answer"]
    results.append(_check("Out-of-scope questions answered with a fact (hard gate: 0)", not answered,
                          f"{len(answered)} of {len(oos)}" + (f": {[c['id'] for c in answered]}" if answered else "")))
    nf = sum(d(c).kind in ("not_found", "refusal", "performance", "privacy") for c in oos)
    results.append(_check("Not-found precision on out-of-scope questions", nf / len(oos) >= 0.95,
                          f"{nf} / {len(oos)} ({nf / len(oos):.1%}; need ≥ 95%; the rest asked which scheme)"))

    # Wrong scheme: no answer may come from a scheme other than the one asked about.
    wrong = []
    for c in facts + paraphrases + hold_pos + [c for c in ambiguous if c["expect"]["kind"] == "answer"]:
        dec, sid = d(c), c["expect"].get("scheme_id")
        if dec.kind == "answer" and r.by_id[dec.chunk_id]["scheme_id"] not in (None, sid):
            wrong.append(c.get("id", c["question"]))
    results.append(_check("Wrong-scheme answers (hard gate: 0)", not wrong, f"{len(wrong)}" + (f": {wrong}" if wrong else "")))

    # Speed.
    q = "what is the exit load of HDFC Mid Cap Fund"
    if dense:
        vec = r.embedder.embed_query(q)
        t0 = time.perf_counter()
        for _ in range(10):
            r.store.query(vec, "hdfc-mid-cap", 22)
        search_ms = (time.perf_counter() - t0) / 10 * 1000
        t0 = time.perf_counter()
        for _ in range(5):
            r.embedder.embed_query(q)
        embed_ms = (time.perf_counter() - t0) / 5 * 1000
        results.append(_check("Speed: ChromaDB search < 10 ms, query embedding < 100 ms",
                              search_ms < 10 and embed_ms < 100, f"search {search_ms:.1f} ms, embedding {embed_ms:.0f} ms"))
    else:
        t0 = time.perf_counter()
        for _ in range(50):
            r.search(q, "hdfc-mid-cap")
        ms = (time.perf_counter() - t0) / 50 * 1000
        results.append(_check("Speed: BM25 search < 5 ms", ms < 5, f"{ms:.2f} ms"))

    # Report: per-topic and per-scheme accuracy, every miss with its top 5.
    by_topic, by_scheme = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for c in facts + general + paraphrases + hold_pos:
        good = is_correct(r, c, d(c))
        t = c["expect"]["topic"]
        by_topic[t][0] += good
        by_topic[t][1] += 1
        if c["expect"].get("scheme_id"):
            by_scheme[c["expect"]["scheme_id"]][0] += good
            by_scheme[c["expect"]["scheme_id"]][1] += 1
    SECTIONS.append("\n".join([
        f"## Phase 3 retrieval ({r.backend_name()})", "",
        "### Accuracy by topic (facts + general + paraphrases + held-out)", "",
        "| Topic | Correct |", "|---|---|",
        *[f"| {t} | {a} / {n} ({a / n:.0%}) |" for t, (a, n) in sorted(by_topic.items())],
        "", "### Accuracy by scheme", "", "| Scheme | Correct |", "|---|---|",
        *[f"| {s.id} | {by_scheme[s.id][0]} / {by_scheme[s.id][1]} |" for s in registry.SCHEMES],
        "", "### Every miss, with the top 5 candidates", "",
        *(["None."] if not misses else
          ["| Set | ID | Question | Expected | Got | Top 5 (score) |", "|---|---|---|---|---|---|", *misses]),
    ]))
    return results


def phase4_checks() -> list[dict]:
    """Phase 4 gate (Doc/eval.md §5): every dataset through the full pipeline, no server, no LLM."""
    import random
    import re
    from collections import Counter, defaultdict

    sys.path.insert(0, str(ROOT))
    from bolosip import pipeline
    from bolosip.formatter import KINDS, validate
    from bolosip.retriever import Retriever
    from bolosip.topics import CORE_TOPICS
    from eval.answer_eval import check_reply, citation_ok

    r = Retriever()
    dense = r.store is not None
    results = [_check("Pipeline starts (retriever in use)", True, r.backend_name())]
    sets = {n: _load_set(n) for n in ("facts", "general", "paraphrases", "holdout", "ambiguous", "out_of_corpus",
                                      "advice", "performance", "pii", "help", "variants")}
    dense_sets = ("general", "paraphrases", "holdout")       # measured on the dense path only (Phase 3)

    rows = []           # (set, case_id, question, expect, reply, problems)
    for name, cases in sets.items():
        for c in cases:
            reply, _ = pipeline.handle(c["question"], {}, retriever=r)
            rows.append((name, c["id"], c["question"], c["expect"], reply, check_reply(r, reply, c["expect"])))
    turns = []
    for conv in _load_set("conversations"):
        ctx = {}
        for i, t in enumerate(conv["turns"]):
            reply, ctx = pipeline.handle(t["q"], ctx, retriever=r)
            turns.append((f"{conv['id']}#{i + 1}", t, reply, check_reply(r, reply, t["expect"])))
    all_replies = [x[4] for x in rows] + [x[2] for x in turns]

    def rate(name, good, total, need, extra=""):
        results.append(_check(name, total and good / total >= need,
                              f"{good} / {total} ({good / total:.1%}; need ≥ {need:.0%}){extra}"))

    core = [x for x in rows if x[0] == "facts" and x[3]["topic"] in CORE_TOPICS]
    rate("Fact accuracy, 135 core questions (AC 1)", sum(not x[5] for x in core), len(core), 0.98)
    rate("Fact accuracy, all 324 fact questions", sum(not x[5] for x in rows if x[0] == "facts"),
         len(sets["facts"]), 0.98)
    bad_format = [x for x in all_replies if validate(x)]
    rate("Format compliance (AC 2): 1–3 sentences, one link, footer; clarify/help none",
         len(all_replies) - len(bad_format), len(all_replies), 1.0)
    bad_cite = [x for x in all_replies if not citation_ok(x)]
    rate("Citation validity (AC 3): scheme page or allowed official domain",
         len(all_replies) - len(bad_cite), len(all_replies), 1.0)
    facts = [x for x in rows if x[0] == "facts"]
    rate("Citation correctness on facts (the scheme's own page)",
         sum(x[4].kind == "answer" and x[4].source.url == x[3]["source_url"] for x in facts), len(facts), 1.0)

    # Reply kind. Expected not_found answered by a guard (e.g. "bitcoin price prediction" -> refusal)
    # is a refusal, not an answer, so it counts as right. Guard negatives have no expected kind.
    def kind_ok(expect, reply):
        k = expect.get("kind")
        return reply.kind == k or (k == "not_found" and reply.kind in ("refusal", "performance", "privacy"))
    kinds = [x for x in rows if x[3].get("kind") and (dense or x[0] not in dense_sets)]
    kinds += [(None, cid, t["q"], t["expect"], reply, p) for cid, t, reply, p in turns
              if dense or not t["expect"].get("dense_only")]
    rate("Reply-kind accuracy, all sets", sum(kind_ok(x[3], x[4]) for x in kinds), len(kinds), 0.97,
         "" if dense else "; general/paraphrase/held-out sets need the dense path and are left out here")

    adv = [x for x in rows if x[0] == "advice" and x[3]["kind"] == "refusal"]
    rate("Refusal recall (AC 4)", sum(x[4].kind == "refusal" for x in adv), len(adv), 1.0)
    perf = [x for x in rows if x[0] == "performance" and x[3]["kind"] == "performance"]
    rate("Performance routed (AC 5)", sum(x[4].kind == "performance" for x in perf), len(perf), 0.97)
    figures = [x for x in all_replies if x.kind == "performance" and re.search(r"\d", x.text)]
    results.append(_check("Figures in performance replies (hard gate: 0)", not figures, str(len(figures))))
    hlp = [x for x in rows if x[0] == "help" and x[3]["kind"] == "help"]
    rate("Help replies (GAP-02)", sum(x[4].kind == "help" for x in hlp), len(hlp), 0.95)
    var = [x for x in rows if x[0] == "variants"]
    rate("Plan variants (GAP-05): Direct value never shown as Regular / IDCW",
         sum(not x[5] for x in var), len(var), 1.0)
    elss = [x for x in rows if re.search(r"(?i)\b(?:elss|tax sav)", x[2]) and x[4].kind in ("answer", "not_found")]
    rate("ELSS wording: says none of the 27 is ELSS",
         sum(bool(re.search(r"(?i)none of the 27|not an ELSS", x[4].text)) for x in elss), len(elss), 1.0)
    ctx_turns = [x for x in turns if dense or not x[1]["expect"].get("dense_only")]
    rate("Context accuracy (conversations.jsonl, in memory)", sum(not x[3] for x in ctx_turns), len(ctx_turns),
         0.95, "" if dense else f"; {len(turns) - len(ctx_turns)} definition turns need the dense path")

    # Report: confusion matrix, samples per kind, every failure.
    matrix = defaultdict(Counter)
    for x in kinds:
        matrix[x[3]["kind"]][x[4].kind] += 1
    rnd = random.Random(4)
    samples = []
    for k in KINDS:
        of_kind = [x for x in rows if x[4].kind == k]
        for x in rnd.sample(of_kind, min(10, len(of_kind))):
            src = x[4].source.url if x[4].source else "—"
            samples.append(f"| {k} | {x[2]} | {x[4].text[:160]} | {src} |")
    answers = [x for x in rows if x[4].kind == "answer"]
    review = rnd.sample(answers, min(30, len(answers)))
    failures = [f"| {x[0]} | {x[1]} | {x[2]} | {'; '.join(x[5])} |" for x in rows if x[5] and
                (dense or x[0] not in dense_sets) and
                not (kind_ok(x[3], x[4]) and x[4].kind != x[3].get("kind") and len(x[5]) == 1)]
    failures += [f"| conversation | {cid} | {t['q']} | {'; '.join(p)} |" for cid, t, _, p in turns
                 if p and (dense or not t["expect"].get("dense_only"))]
    SECTIONS.append("\n".join([
        f"## Phase 4 pipeline ({r.backend_name()})", "",
        "### Reply-kind confusion matrix (expected rows × actual columns)", "",
        "| expected \\ actual | " + " | ".join(KINDS) + " |", "|---|" + "---|" * len(KINDS),
        *[f"| {e} | " + " | ".join(str(matrix[e][a]) for a in KINDS) + " |" for e in KINDS if matrix[e]],
        "", "### Every failing case", "",
        *(["None."] if not failures else ["| Set | ID | Question | Problems |", "|---|---|---|---|", *failures]),
        "", "### 10 sample replies of each kind", "", "| Kind | Question | Reply | Link |", "|---|---|---|---|",
        *samples,
        "", "### Human review (M1): 30 random answers to rate (eval.md §7; two reviewers, ≥ 4.5 / 5)", "",
        "| # | Question | Answer |", "|---|---|---|",
        *[f"| {i} | {x[2]} | {x[4].text} |" for i, x in enumerate(review, 1)],
    ]))
    return results


def phase5_checks() -> list[dict]:
    """Phase 5 gate (Doc/eval.md §5): the Phase 4 behaviour over HTTP, plus storage and safety."""
    import tempfile
    import time
    import unittest
    from concurrent.futures import ThreadPoolExecutor

    sys.path.insert(0, str(ROOT))
    from bolosip import pipeline
    from bolosip.formatter import Reply, Source
    from bolosip.retriever import Retriever
    from eval.answer_eval import check_reply
    from eval.api_harness import LiveServer

    r = Retriever()
    dense = r.store is not None
    results = [_check("Server starts (retriever in use)", True, r.backend_name())]
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db = Path(tmp.name) / "gate.sqlite3"

    def as_reply(body):
        return Reply(body["kind"], body["text"], Source(**body["source"]) if body["source"] else None,
                     body["footer"], body["scheme_id"],
                     tuple(body["candidates"]) if body["candidates"] is not None else None)

    with LiveServer(db, r) as api:
        # API parity: every Phase 4 case, each in a fresh thread, equals the in-memory pipeline.
        names = ("facts", "general", "paraphrases", "holdout", "ambiguous", "out_of_corpus",
                 "advice", "performance", "pii", "help", "variants")
        cases = [c for n in names for c in _load_set(n)]
        diffs = []
        for c in cases:
            tid = api.new_thread()
            status, body = api.ask(tid, c["question"])
            want = pipeline.handle(c["question"], {}, retriever=r)[0].to_dict()
            if status != 200 or body != want:
                diffs.append(c["id"])
        results.append(_check("API parity: every Phase 4 case over HTTP gives the same reply", not diffs,
                              f"{len(cases) - len(diffs)} / {len(cases)}" + (f"; differ: {diffs[:10]}" if diffs else "")))

        # Context over HTTP, and thread isolation with conversations interleaved turn by turn.
        convs = _load_set("conversations")
        tids = [api.new_thread() for _ in convs]
        good = total = leaks = 0
        for i in range(max(len(c["turns"]) for c in convs)):
            for conv, tid in zip(convs, tids):
                if i >= len(conv["turns"]):
                    continue
                turn = conv["turns"][i]
                status, body = api.ask(tid, turn["q"])
                if turn["expect"].get("dense_only") and not dense:
                    continue
                total += 1
                problems = check_reply(r, as_reply(body), turn["expect"]) if status == 200 else ["status"]
                good += not problems
                want = turn["expect"].get("scheme_id")
                if body.get("scheme_id") and want and body["scheme_id"] != want:
                    leaks += 1
        results.append(_check("Context accuracy over HTTP (AC 7), all conversations interleaved",
                              good / total >= 0.98, f"{good} / {total} ({good / total:.1%}; need ≥ 98%)"))
        results.append(_check("Thread isolation: answers about another thread's scheme (hard gate: 0)",
                              leaks == 0, str(leaks)))

        # Concurrency: 20 parallel requests over 5 threads, 10 rounds.
        questions = ["HDFC Mid Cap expense ratio", "its exit load", "its benchmark", "its riskometer"]
        errors = bad_history = 0
        for _ in range(10):
            ts = [api.new_thread() for _ in range(5)]
            with ThreadPoolExecutor(max_workers=20) as pool:
                out = list(pool.map(lambda t: [api.ask(t, q)[0] for q in questions], ts))
            errors += sum(s != 200 for res in out for s in res)
            for t in ts:
                user = [m["text"] for m in api.messages(t) if m["role"] == "user"]
                bad_history += user != questions
        results.append(_check("Concurrency: 20 parallel requests × 5 threads, 10 rounds", errors == 0 and bad_history == 0,
                              f"{errors} errors, {bad_history} incomplete or out-of-order histories"))

        # Personal data: every positive sent, then the DB files and the logs scanned.
        pii = [c for c in _load_set("pii") if c["expect"]["kind"] == "privacy"]
        t = api.new_thread()
        for c in pii:
            api.ask(t, c["question"])
            api.ask(api.new_thread(), c["question"])                 # also as a thread title
        from eval.pii_scan import leaked_values
        leaked = leaked_values(db, [v for c in pii for v in c["expect"].get("values", [])], api.log.getvalue())
        results.append(_check("Personal data in the database or logs (AC 6, hard gate: 0)", not leaked,
                              f"{len(leaked)} of {sum(len(c['expect'].get('values', [])) for c in pii)} values"
                              + (f": {leaked}" if leaked else "")))

        # Latency, extractive, local.
        t = api.new_thread()
        qs = ["HDFC Mid Cap expense ratio", "its exit load", "HDFC Liquid Fund benchmark",
              "What is the ELSS lock-in period?", "hi", "who manages HDFC Gilt Fund", "its riskometer",
              "should I invest in small cap?", "expense ratio of SBI Bluechip", "HDFC Equity exit load"]
        for q in qs:                                   # warm-up: first embedding of each question
            api.ask(t, q)
        times = []
        for q in qs * 20:
            start = time.perf_counter()
            api.ask(t, q)
            times.append((time.perf_counter() - start) * 1000)
        times.sort()
        p50, p95 = times[len(times) // 2], times[int(len(times) * 0.95)]
        on_ci = bool(os.environ.get("CI"))            # shared runners: measured, not enforced
        results.append(_check("Latency (extractive, local): p50 < 50 ms, p95 < 150 ms",
                              on_ci or (p50 < 50 and p95 < 150),
                              f"p50 {p50:.0f} ms, p95 {p95:.0f} ms"
                              + ("; CI runner: reported only, enforced on local runs" if on_ci else "")))
        survivor = api.new_thread()
        api.ask(survivor, "HDFC Small Cap Fund expense ratio")

    # Persistence: a new server on the same database file.
    with LiveServer(db, r) as api:
        hist = api.messages(survivor)
        status, body = api.ask(survivor, "what about its exit load?")
        ok = len(hist) == 2 and status == 200 and body.get("scheme_id") == "hdfc-small-cap"
        results.append(_check("Persistence: history and last_scheme survive a restart", ok,
                              f"{len(hist)} messages kept; follow-up scheme {body.get('scheme_id')}"))
    tmp.cleanup()

    # Request safety: the unit tests for IN-01–12, GAP-08, GAP-09 and SEC-01–07 (tests/test_api.py).
    import tests.test_api as t_api
    groups = {
        "Input validation (IN-01–12): correct status codes": [t_api.TestInputValidation],
        "Request origin checks (GAP-08): wrong Host / foreign Origin / non-JSON POST blocked": [t_api.TestOriginChecks],
        "Rate limit (GAP-09): the 31st message in a minute gets 429": [t_api.TestRateLimit],
        "Security cases (SEC-01–08, THR-06)": [t_api.TestSecurity],
    }
    for name, classes in groups.items():
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in classes)
        res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        bad = [str(x[0]).split(" ")[0] for x in res.failures + res.errors]
        results.append(_check(name, res.wasSuccessful(),
                              f"{res.testsRun - len(bad)} / {res.testsRun} tests" + (f"; failed: {bad}" if bad else "")))
    return results


def phase6_checks() -> list[dict]:
    """Phase 6 gate (Doc/eval.md §5): the web page. Scripted checks run here; the browser
    checks are recorded in eval/manual/phase6_ui_check.json (plan Phase 6 task 9)."""
    import unittest

    sys.path.insert(0, str(ROOT))
    import tests.test_web as t_web

    results = []
    groups = {
        "Page is self-contained: no external scripts, fonts or trackers": [t_web.TestSelfContained],
        "Content: sticky disclaimer, 500-character input, privacy hint, kinds, no unbacked claims": [t_web.TestContent],
        "Contrast (WCAG AA, both themes) and hairline borders": [t_web.TestContrast],
        "Served by server.py with security headers (CSP, no framing)": [t_web.TestServedPage],
    }
    for name, classes in groups.items():
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in classes)
        res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        bad = [str(x[0]).split(" ")[0] for x in res.failures + res.errors]
        results.append(_check(name, res.wasSuccessful(),
                              f"{res.testsRun - len(bad)} / {res.testsRun} tests" + (f"; failed: {bad}" if bad else "")))

    manual_path = ROOT / "eval" / "manual" / "phase6_ui_check.json"
    manual = json.loads(manual_path.read_text(encoding="utf-8"))
    checks = manual["checks"]
    failed = [c["id"] for c in checks if c["result"] != "pass"]
    required = {"AC9", "AC9-scroll", "EX", "UI-01", "UI-06", "UI-07", "UI-11", "UI-12-keyboard", "TABS"}
    missing = sorted(required - {c["id"] for c in checks})
    results.append(_check(f"Browser checks recorded ({manual['date']})", not failed and not missing,
                          f"{len(checks) - len(failed)} / {len(checks)} pass" +
                          (f"; failed: {failed}" if failed else "") + (f"; missing: {missing}" if missing else "")))
    SECTIONS.append("\n".join([
        "## Phase 6 web UI", "", f"Method: {manual['method']}", "",
        "| Check | Result | Notes |", "|---|---|---|",
        *[f"| {c['id']}: {c['check']} | {c['result']} | {c['notes']} |" for c in checks],
        "", "### Still to do by hand (not part of the automated gate)", "",
        *[f"- {p['id']}: {p['check']}" for p in manual.get("pending", [])],
    ]))
    return results


PHASE_CHECKS = {0: phase0_checks, 1: phase1_checks, 2: phase2_checks, 3: phase3_checks, 4: phase4_checks,
                5: phase5_checks, 6: phase6_checks}


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
