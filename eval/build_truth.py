"""Independent ground truth for scheme facts (Doc/eval.md §3, principle E4).

Reads the 27 saved scheme pages in data/raw/ with its OWN small parser (it does
not import ingest.py) and writes eval/datasets/facts.jsonl: one question per
scheme × topic, with the values a correct answer must contain. The Phase 1
gate checks every corpus chunk against these values, so a bug in ingest.py's
templates can't grade itself.

Usage:  python -m eval.build_truth          (rewrite eval/datasets/facts.jsonl)
"""
from __future__ import annotations

import datetime as dt
import html.parser
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DATASET = ROOT / "eval" / "datasets" / "facts.jsonl"
FACTSHEET = "https://www.hdfcfund.com/mutual-funds/factsheets"

sys.path.insert(0, str(ROOT))
from bolosip.registry import SCHEMES  # noqa: E402  (registry only: IDs, names, URLs)

CORE = ("expense_ratio", "exit_load", "min_investment", "riskometer", "benchmark")
QUESTIONS = {
    "expense_ratio": "What is the expense ratio of {name}?",
    "exit_load": "What is the exit load of {name}?",
    "min_investment": "What is the minimum SIP amount for {name}?",
    "riskometer": "What is the riskometer level of {name}?",
    "benchmark": "What is the benchmark index of {name}?",
    "lock_in": "Is there a lock-in period for {name}?",
    "fund_manager": "Who manages {name}?",
    "category": "What type of scheme is {name}?",
    "nav": "What is the NAV of {name}?",
    "aum": "What is the fund size of {name}?",
    "scheme_details": "What is the ISIN of {name}?",
    "stamp_duty": "What stamp duty applies to {name}?",
}


class _NextData(html.parser.HTMLParser):
    """Collects the text of <script id="__NEXT_DATA__"> using the stdlib HTML parser."""

    def __init__(self):
        super().__init__()
        self._inside = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._inside = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._inside = False

    def handle_data(self, data):
        if self._inside:
            self.parts.append(data)


def page_data(path: Path) -> dict:
    p = _NextData()
    p.feed(path.read_text(encoding="utf-8"))
    return json.loads("".join(p.parts))["props"]["pageProps"]["mfServerSideData"]


def _grouped(amount: float) -> str:
    """Indian grouping written differently from ingest.inr: builds groups right to left."""
    rupees, paise = divmod(round(amount * 100), 100)
    s = str(rupees)
    groups = [s[-3:]] if len(s) > 3 else [s]
    s = s[:-3]
    while s:
        groups.insert(0, s[-2:])
        s = s[:-2]
    text = ",".join(groups) if len(str(rupees)) > 3 else str(rupees)
    return text if paise == 0 else f"{text}.{paise:02d}"


def _date(value: str) -> str:
    for fmt in ("%d-%b-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(value, fmt).strftime("%d %b %Y")
        except ValueError:
            pass
    return value


def expected(d: dict) -> dict[str, list[str]]:
    """Values (case-insensitive substrings) a correct fact must contain, per topic."""
    out: dict[str, list[str]] = {}
    out["expense_ratio"] = [f"{float(d['expense_ratio']):.2f}%"]

    load = " ".join((d.get("exit_load") or "").split())
    if load.strip(". ").lower() in ("", "nil", "none"):
        out["exit_load"] = ["no exit load"]
    else:
        pcts = re.findall(r"\d+(?:\.\d+)?%", load)
        spans = [f"within {n} {u.lower()}" for n, u in re.findall(r"within (\d+) ([A-Za-z]+)", load)]
        out["exit_load"] = pcts + spans

    vals = [f"₹{_grouped(d['min_sip_investment'])}"]
    vals.append("blocked" if d.get("lumpsum_allowed") is False else f"₹{_grouped(d['min_investment_amount'])}")
    out["min_investment"] = vals

    code = str(d.get("scheme_code"))
    risk = next(s["risk"] for s in d["return_stats"] if str(s.get("scheme_code")) == code)
    out["riskometer"] = [f'"{risk}"']

    bm = " ".join((d.get("benchmark_name") or "").split())
    out["benchmark"] = ["does not state an official benchmark"] if bm.lower().startswith("groww") else [bm]

    out["lock_in"] = ["no lock-in period"] if not any((d.get("lock_in") or {}).values()) else ["lock-in period of"]
    out["fund_manager"] = sorted({m["person_name"].strip() for m in d.get("fund_manager_details") or []})
    out["category"] = [d["description"].strip()[:60]]
    out["nav"] = [f"₹{d['nav']}", _date(d["nav_date"])]
    out["aum"] = [f"₹{_grouped(d['aum'])} crore"]
    out["scheme_details"] = [d["isin"], _date(d["launch_date"])]
    out["stamp_duty"] = [d["stamp_duty"].strip()]
    return out


def build() -> list[dict]:
    cases = []
    for s in SCHEMES:
        d = page_data(RAW / f"{s.id}.html")
        exp = expected(d)
        for topic, question in QUESTIONS.items():
            placeholder = topic == "benchmark" and exp[topic] == ["does not state an official benchmark"]
            cases.append({
                "id": f"FACT-{s.id}-{topic}",
                "ref": "AC1" if topic in CORE else "AC1-extended",
                "question": question.format(name=s.name),
                "expect": {
                    "kind": "answer",
                    "scheme_id": s.id,
                    "topic": topic,
                    "contains": exp[topic],
                    "source_url": FACTSHEET if placeholder else s.url,
                },
            })
    return cases


def write(cases: list[dict]) -> None:
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    with open(DATASET, "w", encoding="utf-8", newline="\n") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def load() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    cases = build()
    write(cases)
    core = sum(1 for c in cases if c["ref"] == "AC1")
    print(f"wrote {len(cases)} cases ({core} core, {len(cases) - core} extended) -> {DATASET.relative_to(ROOT)}")
