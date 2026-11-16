"""Build the BoloSIP corpus.

Fetches the five HDFC scheme pages listed in the problem statement, extracts the
structured scheme data embedded in each page, and turns it into small, single-fact
chunks. Curated process/education notes from official sources (HDFC MF, AMFI, SEBI,
CAMS, MF Central) are merged in from data/official_docs.json.

Run:  python ingest.py            (re-fetch and rebuild data/corpus.json)
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RAW = DATA / "raw"  # last successfully fetched page per scheme (offline fallback)

SCHEMES = {
    "hdfc-mid-cap": {
        "url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        "aliases": ["mid cap", "midcap", "mid-cap", "mid cap opportunities"],
    },
    "hdfc-small-cap": {
        "url": "https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth",
        "aliases": ["small cap", "smallcap", "small-cap"],
    },
    "hdfc-large-cap": {
        "url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
        "aliases": ["large cap", "largecap", "large-cap", "top 100"],
    },
    "hdfc-silver-etf-fof": {
        "url": "https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth",
        "aliases": ["silver", "silver etf", "silver fof", "silver etf fof"],
    },
    "hdfc-multi-cap": {
        "url": "https://groww.in/mutual-funds/hdfc-multi-cap-fund-direct-growth",
        "aliases": ["multi cap", "multicap", "multi-cap"],
    },
}

FACTSHEET_URL = "https://www.hdfcfund.com/mutual-funds/factsheets"

# Extra words attached to each chunk so lexical retrieval matches how people ask.
TOPIC_KEYWORDS = {
    "expense_ratio": "expense ratio ter total expense ratio cost charges fee fees annual",
    "exit_load": "exit load redemption charge penalty withdraw early redeem",
    "min_investment": "minimum sip amount min sip lumpsum lump sum minimum investment start",
    "riskometer": "riskometer risk level risk classification risky risk grade",
    "benchmark": "benchmark index tracks compared against tri",
    "lock_in": "lock in lock-in lockin period elss locked tax saving",
    "fund_manager": "fund manager managed by who manages manager",
    "category": "category type objective investment objective what is scheme about",
    "nav": "nav net asset value price unit price",
    "aum": "aum fund size assets under management corpus size",
    "scheme_details": "launch date inception isin registrar rta plan direct growth",
    "stamp_duty": "stamp duty",
}


def _ssl_context() -> ssl.SSLContext:
    # Certificates are still fully verified. Python 3.13+ also enables
    # VERIFY_X509_STRICT, which rejects some real-world chains (and many corporate /
    # antivirus TLS proxies), so only that extra strictness flag is relaxed.
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return ctx


def _fetch_urllib(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as r:
        return r.read().decode("utf-8", errors="replace")


def _fetch_curl(url: str) -> str:
    # Some sites reject Python's TLS client fingerprint but accept curl.
    exe = shutil.which("curl")
    if not exe:
        raise RuntimeError("curl not available")
    out = subprocess.run([exe, "-sSL", "--fail", "--max-time", "30", "-A", "Mozilla/5.0", url],
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8", errors="replace")


def fetch(url: str) -> str:
    try:
        return _fetch_urllib(url)
    except Exception as first:
        try:
            return _fetch_curl(url)
        except Exception:
            raise first


def parse_scheme(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("embedded scheme data not found")
    data = json.loads(m.group(1))["props"]["pageProps"]["mfServerSideData"]
    risk = re.search(r'"risk":"([^"]+)"', html)
    data["_riskometer"] = risk.group(1) if risk else None
    return data


def inr(n) -> str:
    """Indian digit grouping: 100687.07 -> 1,00,687.07"""
    whole, _, frac = f"{float(n):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = f"{head},{tail}"
    return f"{whole}.{frac}" if frac != "00" else whole


def iso_to_human(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "")).strftime("%d %b %Y")
    except ValueError:
        return s


def scheme_chunks(sid: str, url: str, d: dict, fetched: str) -> list[dict]:
    name = d["scheme_name"]
    chunks: list[dict] = []

    def add(topic: str, text: str):
        chunks.append({
            "id": f"{sid}:{topic}",
            "scheme_id": sid,
            "scheme_name": name,
            "topic": topic,
            "text": text,
            "source_url": url,
            "source_name": f"{name} scheme page",
            "as_of": fetched,
            "keywords": TOPIC_KEYWORDS.get(topic, ""),
        })

    er_date = iso_to_human((d.get("historic_fund_expense") or [{}])[0].get("as_on_date"))
    add("expense_ratio",
        f"The expense ratio (TER) of {name} is {float(d['expense_ratio']):.2f}% per annum"
        + (f", as on {er_date}." if er_date else "."))

    exit_load = (d.get("exit_load") or "Nil").strip().rstrip(".")
    add("exit_load", f"Exit load for {name}: {exit_load[0].lower() + exit_load[1:]}.")

    add("min_investment",
        f"The minimum SIP amount for {name} is ₹{inr(d['min_sip_investment'])}. "
        f"The minimum first lump-sum investment is ₹{inr(d['min_investment_amount'])} and "
        f"additional purchases start at ₹{inr(d['mini_additional_investment'])}.")

    if d.get("_riskometer"):
        add("riskometer", f"{name} is classified as \"{d['_riskometer']}\" risk on the riskometer.")

    add("benchmark", f"The benchmark index of {name} is the {d['benchmark_name']}.")

    li = d.get("lock_in") or {}
    if any(li.get(k) for k in ("years", "months", "days")):
        parts = [f"{li[k]} {k}" for k in ("years", "months", "days") if li.get(k)]
        add("lock_in", f"{name} has a lock-in period of {' '.join(parts)}.")
    else:
        add("lock_in", f"{name} has no lock-in period, as it is not an ELSS (tax-saving) scheme; "
                       f"exit load rules still apply on early redemption.")

    managers = [m["person_name"] for m in d.get("fund_manager_details") or [] if m.get("person_name")]
    managers = list(dict.fromkeys(managers)) or [d.get("fund_manager")]
    managers = [m for m in managers if m]
    who = managers[0] if len(managers) == 1 else ", ".join(managers[:-1]) + " and " + managers[-1]
    add("fund_manager", f"{name} is managed by {who}.")

    add("category",
        f"{name} is a {d['sub_category']} {d['category'].lower()} scheme of {d['fund_house']}. "
        f"Objective: {d['description'].strip()}")

    add("nav", f"The NAV of {name} was ₹{d['nav']} as on {d['nav_date']}.")

    add("aum", f"The fund size (AUM) of {name} is ₹{inr(d['aum'])} crore.")

    launch = d.get("launch_date")
    add("scheme_details",
        f"{name} ({d.get('plan_type', 'Direct')} plan, {d.get('scheme_type', 'Growth')} option) was launched on {launch}. "
        f"Its ISIN is {d['isin']} and its registrar (RTA) is {d.get('registrar_agent', 'CAMS')}.")

    if d.get("stamp_duty"):
        add("stamp_duty", f"Stamp duty of {d['stamp_duty']} applies to purchases in {name}.")

    return chunks


def main() -> int:
    DATA.mkdir(exist_ok=True)
    fetched = dt.date.today().strftime("%d %b %Y")
    chunks: list[dict] = []
    schemes_meta = {}
    for sid, cfg in SCHEMES.items():
        print(f"fetching {cfg['url']}")
        snapshot = RAW / f"{sid}.html"
        try:
            html = fetch(cfg["url"])
            d = parse_scheme(html)
            RAW.mkdir(exist_ok=True)
            snapshot.write_text(html, encoding="utf-8")
            as_of = fetched
        except Exception as e:
            if not snapshot.exists():
                print(f"  FAILED: {e}", file=sys.stderr)
                continue
            print(f"  live fetch failed ({e}); using saved snapshot {snapshot.name}", file=sys.stderr)
            d = parse_scheme(snapshot.read_text(encoding="utf-8"))
            as_of = dt.date.fromtimestamp(snapshot.stat().st_mtime).strftime("%d %b %Y")
        chunks += scheme_chunks(sid, cfg["url"], d, as_of)
        schemes_meta[sid] = {
            "name": d["scheme_name"],
            "url": cfg["url"],
            "aliases": cfg["aliases"],
            "factsheet_url": FACTSHEET_URL,
        }

    official = json.loads((DATA / "official_docs.json").read_text(encoding="utf-8"))
    for doc in official["docs"]:
        doc = {**doc, "scheme_id": None, "scheme_name": None, "as_of": official["reviewed_on"]}
        chunks.append(doc)

    out = {
        "built_on": fetched,
        "factsheet_url": FACTSHEET_URL,
        "schemes": schemes_meta,
        "chunks": chunks,
    }
    (DATA / "corpus.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(chunks)} chunks for {len(schemes_meta)} schemes -> data/corpus.json")
    return 0 if len(schemes_meta) == len(SCHEMES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
