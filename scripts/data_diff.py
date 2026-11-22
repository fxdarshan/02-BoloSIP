"""Change report for the daily data refresh (Phase 7), and the rule that can block it.

    python scripts/data_diff.py OLD_CORPUS NEW_CORPUS [--summary FILE] [--github-output FILE]

Compares two `corpus.json` files fact by fact and sorts every change:

* daily    NAV, fund size and "as on" dates: expected every day
* minor    expense ratio moved by at most 0.25 percentage points
* stable   any other change to a scheme fact (expense ratio by more than 0.25 pp, exit
           load, riskometer, benchmark, fund managers, minimum SIP, ISIN, launch date…)
* official a hand-curated official note changed (only ever by a repo edit)

The commit is **blocked** (exit code 3) when a scheme is missing from the new corpus or
more than 5 stable facts changed in one run: a parser or page-structure change is likelier
than that many real changes overnight. Prints a Markdown report; with --summary it is also
appended to that file (the workflow passes $GITHUB_STEP_SUMMARY), and with --github-output
the counts are written as step outputs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bolosip import registry  # noqa: E402
from bolosip.embedder import mask_daily_values  # noqa: E402

MAX_STABLE_CHANGES = 5
TER_MINOR_PP = 0.25
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")


@dataclass
class Report:
    daily: list[tuple[str, str, str]] = field(default_factory=list)      # (id, before, after)
    minor: list[tuple[str, str, str]] = field(default_factory=list)
    stable: list[tuple[str, str, str]] = field(default_factory=list)
    official: list[tuple[str, str, str]] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    missing_schemes: list[str] = field(default_factory=list)
    snapshot_schemes: list[str] = field(default_factory=list)
    file_changed: bool = False
    built_on: tuple[str | None, str | None] = (None, None)

    @property
    def blocked_reasons(self) -> list[str]:
        reasons = []
        if self.missing_schemes:
            reasons.append(f"scheme(s) missing from the new corpus: {', '.join(self.missing_schemes)}")
        if len(self.stable) > MAX_STABLE_CHANGES:
            reasons.append(f"{len(self.stable)} stable facts changed in one run (limit {MAX_STABLE_CHANGES})")
        return reasons

    @property
    def facts_changed(self) -> int:
        return len(self.daily) + len(self.minor) + len(self.stable) + len(self.official) + len(self.added)


def _ter_only_change(before: str, after: str) -> float | None:
    """If two expense-ratio texts differ only in the percentage, the change in pp."""
    if _PERCENT.sub("X%", before) != _PERCENT.sub("X%", after):
        return None
    b, a = _PERCENT.findall(before), _PERCENT.findall(after)
    if len(a) != len(b) or not a:
        return None
    return max(abs(float(x) - float(y)) for x, y in zip(b, a))


def compare(old: dict, new: dict) -> Report:
    rep = Report(built_on=(old.get("built_on"), new.get("built_on")))
    rep.file_changed = json.dumps(old, sort_keys=True) != json.dumps(new, sort_keys=True)
    old_chunks = {c["id"]: c for c in old.get("chunks", [])}
    new_chunks = {c["id"]: c for c in new.get("chunks", [])}

    new_schemes = {c["scheme_id"] for c in new_chunks.values() if c.get("scheme_id")}
    rep.missing_schemes = [s.id for s in registry.SCHEMES if s.id not in new_schemes]
    rep.snapshot_schemes = sorted(sid for sid, src in (new.get("sources") or {}).items()
                                  if src.get("origin") != "live")

    for cid, nc in new_chunks.items():
        oc = old_chunks.get(cid)
        if oc is None:
            rep.added.append(cid)
            continue
        before, after = oc["text"], nc["text"]
        if before == after:
            continue
        row = (cid, before, after)
        if not nc.get("scheme_id"):
            rep.official.append(row)
        elif mask_daily_values(oc) == mask_daily_values(nc):
            rep.daily.append(row)
        elif nc.get("topic") == "expense_ratio" and (pp := _ter_only_change(
                mask_daily_values(oc), mask_daily_values(nc))) is not None and pp <= TER_MINOR_PP:
            rep.minor.append(row)
        else:
            rep.stable.append(row)
    rep.removed = sorted(set(old_chunks) - set(new_chunks))
    return rep


def markdown(rep: Report) -> str:
    def table(rows, limit=None):
        out = ["| Fact | Before | After |", "|---|---|---|"]
        for cid, b, a in rows[:limit]:
            out.append(f"| `{cid}` | {b.replace('|', '/')} | {a.replace('|', '/')} |")
        if limit and len(rows) > limit:
            out.append(f"| … | {len(rows) - limit} more | |")
        return out

    lines = [f"## BoloSIP data refresh: {rep.built_on[1]}", "",
             f"Previous data: {rep.built_on[0]}. Facts changed: **{rep.facts_changed}** "
             f"({len(rep.daily)} daily, {len(rep.minor)} minor expense-ratio, {len(rep.stable)} stable, "
             f"{len(rep.official)} official notes, {len(rep.added)} added, {len(rep.removed)} removed).", ""]
    if rep.snapshot_schemes:
        lines += [f"⚠️ Not fetched live in this run (taken from the last saved snapshot): "
                  f"{', '.join(rep.snapshot_schemes)}", ""]
    reasons = rep.blocked_reasons
    lines += [f"**Verdict: {'BLOCKED: ' + '; '.join(reasons) if reasons else 'OK to commit'}**", ""]
    if rep.stable:
        lines += ["### Stable facts changed (please review)", "", *table(rep.stable), ""]
    if rep.minor:
        lines += ["### Expense ratio moved by ≤ 0.25 pp", "", *table(rep.minor), ""]
    if rep.official:
        lines += ["### Official notes changed", "", *table(rep.official), ""]
    if rep.added or rep.removed:
        lines += [f"Added: {', '.join(rep.added) or 'none'}. Removed: {', '.join(rep.removed) or 'none'}.", ""]
    if rep.daily:
        lines += ["### Daily values (NAV, fund size, dates)", "", *table(rep.daily, limit=10), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Compare two corpus.json files (Phase 7 change report).")
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--summary", type=Path, help="append the Markdown report to this file")
    ap.add_argument("--github-output", type=Path, help="write step outputs (key=value) to this file")
    args = ap.parse_args(argv)
    old = json.loads(args.old.read_text(encoding="utf-8"))
    new = json.loads(args.new.read_text(encoding="utf-8"))
    rep = compare(old, new)
    text = markdown(rep)
    if hasattr(sys.stdout, "reconfigure"):                 # ₹ and ≤ on a Windows console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as f:
            f.write(f"changed={'true' if rep.file_changed else 'false'}\n")
            f.write(f"facts_changed={rep.facts_changed}\n")
            f.write(f"stable_changes={len(rep.stable)}\n")
            f.write(f"snapshot_schemes={','.join(rep.snapshot_schemes)}\n")
            f.write(f"blocked={'true' if rep.blocked_reasons else 'false'}\n")
    return 3 if rep.blocked_reasons else 0


if __name__ == "__main__":
    sys.exit(main())
