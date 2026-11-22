"""Build the BoloSIP corpus (data/corpus.json).

Fetches exactly the 27 Groww HDFC scheme pages in bolosip/registry.py (no other
URL), reads the structured data embedded in each page, and turns it into small
single-fact chunks (12 per scheme). Hand-curated official notes from
data/official_docs.json are merged in. Nothing is written unless every check
passes. See Doc/architecture.md §15 and Doc/Implementation-plan.md Phase 1.

Usage:
    python ingest.py             fetch live (falls back to saved snapshots)
    python ingest.py --offline   use saved snapshots only (no network)

Exit codes:
    0  corpus written, every page fetched live
    1  corpus written, at least one page came from a saved snapshot
    2  corpus NOT written (registry problem, missing page, failed check, or
       another run holds the lock); the previous corpus.json is unchanged
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from bolosip import registry
from bolosip.config import HDFC_FACTSHEET_URL, OFFICIAL_DOMAINS
from bolosip.registry import Scheme
from bolosip.textutil import BANNED_JUDGEMENT, RETURN_FIGURE, URL, split_sentences, utf8_output
from bolosip.topics import OFFICIAL_TOPICS, SCHEME_TOPICS, SEBI_RISK_LEVELS, TOPIC_KEYWORDS

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"                       # last good page per scheme
FETCH_LOG = RAW / "fetched.json"         # when each snapshot was fetched
CORPUS = DATA / "corpus.json"
OFFICIAL_DOCS = DATA / "official_docs.json"
LOCK = DATA / ".ingest.lock"
LOCK_STALE_SECONDS = 30 * 60

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
GROUP_NAMES = {"Equity": "Equity", "Hybrid": "Hybrid", "Debt": "Debt", "FoF": "Fund of Funds"}


class IngestError(Exception):
    """A problem that stops the corpus being written."""


def today() -> str:
    return dt.datetime.now(IST).strftime("%d %b %Y")


# ---------------------------------------------------------------------------
# Fetching: only registry URLs, urllib first, then curl
# ---------------------------------------------------------------------------

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
    # Groww rejects Python's TLS client fingerprint (403) but accepts curl.
    exe = shutil.which("curl")
    if not exe:
        raise RuntimeError("curl not available")
    out = subprocess.run([exe, "-sSL", "--fail", "--max-time", "30", "-A", "Mozilla/5.0", url],
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8", errors="replace")


def fetch(url: str) -> str:
    """Fetch one page. Refuses any URL that isn't one of the 27 registry URLs."""
    if url not in registry.ALLOWED_URLS:
        raise IngestError(f"refusing to fetch a URL outside the registry: {url}")
    try:
        return _fetch_urllib(url)
    except Exception as first:
        try:
            return _fetch_curl(url)
        except Exception:
            raise first


# ---------------------------------------------------------------------------
# Parsing the page's embedded data
# ---------------------------------------------------------------------------

def parse_page(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise IngestError("embedded page data (__NEXT_DATA__) not found")
    try:
        return json.loads(m.group(1))["props"]["pageProps"]["mfServerSideData"]
    except (ValueError, KeyError, TypeError) as e:
        raise IngestError(f"embedded page data has an unexpected shape: {e}") from None


def riskometer(d: dict) -> str:
    """The scheme's own riskometer level (GAP-03).

    Read from ``return_stats`` for this scheme's code (never the first "risk" in
    the page, which can belong to a peer fund) and cross-checked against the
    "Risk is …" sentence in ``meta_desc``.
    """
    code = str(d.get("scheme_code") or "")
    stats = [s for s in d.get("return_stats") or [] if str(s.get("scheme_code")) == code]
    level = (stats[0].get("risk") if stats else None) or ""
    level = " ".join(str(level).split())
    if level not in SEBI_RISK_LEVELS:
        raise IngestError(f"riskometer {level!r} is not one of SEBI's 6 levels")
    m = re.search(r"Risk is ([A-Za-z ]+?)\.?\s*$", d.get("meta_desc") or "")
    if m and m.group(1).strip().lower() != level.lower():
        raise IngestError(f"riskometer mismatch: data says {level!r}, page summary says {m.group(1)!r}")
    return level


def check_identity(s: Scheme, d: dict) -> None:
    if d.get("search_id") != s.slug:
        raise IngestError(f"page is for {d.get('search_id')!r}, expected {s.slug!r} (redirect?)")
    if d.get("isin") != s.isin:
        raise IngestError(f"ISIN {d.get('isin')!r} does not match registry {s.isin!r}")
    if d.get("closed_scheme"):
        raise IngestError("scheme is marked closed on its page")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def inr(n) -> str:
    """Indian digit grouping: 100687.07 -> 1,00,687.07 ; 100 -> 100"""
    whole, _, frac = f"{float(n):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = f"{head},{tail}"
    return whole if frac == "00" else f"{whole}.{frac}"


def human_date(value: str | None) -> str | None:
    """'2026-11-12T00:00:00' or '13-Nov-2026' -> '12 Nov 2026'."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(value.split(".")[0].rstrip("Z"), fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    return value


def clean(value) -> str:
    return " ".join(str(value or "").split())


def join_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def exit_load_text(label: str, raw: str | None) -> str:
    e = clean(raw).rstrip(". ")
    e = re.sub(r",(?=\S)", ", ", e)
    e = re.sub(r"\b(Days|Day|Months|Month|Years|Year)\b", lambda m: m.group(1).lower(), e)
    if e.lower() in ("", "nil", "none", "0", "0%", "no exit load", "na", "n/a"):
        return f"There is no exit load for {label}."
    m = re.match(r"(?i)exit load\s+of\s+(.+)", e)
    if m:
        return f"{label} has an exit load of {m.group(1)}."
    # e.g. "Exit Load for units in excess of 15% of the investment,1% will be charged for ..."
    m = re.match(r"(?i)exit load\s+for\s+(units[^,]+),\s*(.+)", e)
    if m:
        return f"For {label}, an exit load applies to {m.group(1)}: {m.group(2)}."
    return f"Exit load for {label}: {e}."


def is_placeholder_benchmark(name: str, code: str) -> bool:
    """Groww internal labels (e.g. 'Groww Equity Hybrid' / 'GROWWEH') are not official benchmarks."""
    return not name or name.lower().startswith("groww") or code.upper().startswith("GROWW")


# ---------------------------------------------------------------------------
# Chunks: 12 single-fact chunks per scheme
# ---------------------------------------------------------------------------

def scheme_chunks(s: Scheme, d: dict, as_of: str, factsheet_as_of: str) -> list[dict]:
    label = s.label
    chunks: list[dict] = []

    def add(topic: str, text: str, *, url: str = s.url, source_name: str | None = None,
            date: str = as_of):
        chunks.append({
            "id": f"{s.id}:{topic}",
            "scheme_id": s.id,
            "scheme_name": label,
            "topic": topic,
            "text": text,
            "keywords": TOPIC_KEYWORDS[topic],
            "source_url": url,
            "source_name": source_name or f"{s.name} – Groww scheme page",
            "as_of": date,
        })

    # expense_ratio
    try:
        er = float(d.get("expense_ratio"))
    except (TypeError, ValueError):
        raise IngestError(f"expense ratio missing or not a number: {d.get('expense_ratio')!r}") from None
    if not 0 < er <= 3:
        raise IngestError(f"expense ratio {er}% is outside 0–3%")
    er_date = human_date((d.get("historic_fund_expense") or [{}])[0].get("as_on_date"))
    add("expense_ratio", f"The expense ratio (TER) of {label} is {er:.2f}% per annum"
                         + (f", as on {er_date}." if er_date else "."))

    # exit_load
    add("exit_load", exit_load_text(label, d.get("exit_load")))

    # min_investment
    sip, lump, extra = d.get("min_sip_investment"), d.get("min_investment_amount"), d.get("mini_additional_investment")
    parts = []
    if d.get("sip_allowed") is False:
        parts.append(f"SIP investments in {label} are currently not accepted.")
    else:
        if not isinstance(sip, (int, float)) or sip <= 0 or sip != int(sip):
            raise IngestError(f"minimum SIP {sip!r} is not a positive whole number")
        parts.append(f"The minimum SIP amount for {label} is ₹{inr(sip)}.")
    if d.get("lumpsum_allowed") is False:
        parts.append("One-time (lump-sum) investments in this scheme are currently blocked by the fund house.")
    else:
        if not isinstance(lump, (int, float)) or lump <= 0:
            raise IngestError(f"minimum lump-sum {lump!r} is not positive")
        more = f" and additional purchases start at ₹{inr(extra)}" if isinstance(extra, (int, float)) and extra > 0 else ""
        parts.append(f"The minimum first lump-sum investment is ₹{inr(lump)}{more}.")
    add("min_investment", " ".join(parts))

    # riskometer
    add("riskometer", f'{label} is classified as "{riskometer(d)}" risk on the riskometer.')

    # benchmark (Groww placeholder labels are not presented as facts)
    bm, bm_code = clean(d.get("benchmark_name")), clean(d.get("benchmark"))
    if is_placeholder_benchmark(bm, bm_code):
        add("benchmark",
            f"The scheme page for {label} does not state an official benchmark index. "
            "HDFC Mutual Fund's monthly factsheet lists the benchmark of each scheme.",
            url=HDFC_FACTSHEET_URL, source_name="HDFC Mutual Fund – Factsheets", date=factsheet_as_of)
    else:
        add("benchmark", f"The benchmark index of {label} is the {bm}.")

    # lock_in
    li = d.get("lock_in") or {}
    if any(li.get(k) for k in ("years", "months", "days")):
        span = " ".join(f"{li[k]} {k}" for k in ("years", "months", "days") if li.get(k))
        add("lock_in", f"{label} has a lock-in period of {span}.")
    else:
        add("lock_in", f"{label} has no lock-in period, as it is not an ELSS (tax-saving) scheme; "
                       "exit load rules still apply on early redemption.")

    # fund_manager (current list; the single 'fund_manager' field can be stale)
    names = list(dict.fromkeys(clean(m.get("person_name")) for m in d.get("fund_manager_details") or []
                               if clean(m.get("person_name"))))
    if not names and clean(d.get("fund_manager")):
        names = [clean(d.get("fund_manager"))]
    if not names:
        raise IngestError("no fund manager listed")
    add("fund_manager", f"{label} is managed by {join_names(names)}.")

    # category (+ first sentence of the stated objective)
    objective = split_sentences(clean(d.get("description")))
    text = f"{label} is classified as {s.category} in the {GROUP_NAMES[s.group]} group of HDFC Mutual Fund schemes."
    if objective:
        text += f" Its stated objective: {objective[0]}"
        if not text.endswith((".", "!", "?")):
            text += "."
    add("category", text)

    # nav
    nav, nav_date = d.get("nav"), human_date(d.get("nav_date"))
    if not isinstance(nav, (int, float)) or nav <= 0 or not nav_date:
        raise IngestError(f"NAV {nav!r} / date {d.get('nav_date')!r} missing")
    add("nav", f"The NAV of {label} was ₹{nav} as on {nav_date}.")

    # aum
    aum = d.get("aum")
    if not isinstance(aum, (int, float)) or aum <= 0:
        raise IngestError(f"AUM {aum!r} missing")
    add("aum", f"The fund size (AUM) of {label} is ₹{inr(aum)} crore.")

    # scheme_details
    launch = human_date(d.get("launch_date"))
    rta = clean(d.get("registrar_agent")).upper() or "not stated"
    add("scheme_details",
        f"The Direct Plan (Growth option) of {s.name} was launched on {launch}. "
        f"Its ISIN is {s.isin}, and its registrar and transfer agent (RTA) is {rta}.")

    # stamp_duty
    stamp = clean(d.get("stamp_duty"))
    if not stamp:
        raise IngestError("stamp duty missing")
    add("stamp_duty", f"Stamp duty of {stamp} applies to purchases in {label}.")

    return chunks


# ---------------------------------------------------------------------------
# Validation (architecture §15)
# ---------------------------------------------------------------------------

def _allowed_source(url: str) -> bool:
    if url in registry.ALLOWED_URLS:
        return True
    host = re.sub(r"^https://", "", url).split("/", 1)[0].lower()
    return url.startswith("https://") and any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def validate_corpus(corpus: dict) -> list[str]:
    """Every problem that should stop the corpus being written."""
    problems: list[str] = []
    chunks = corpus.get("chunks") or []
    seen_ids: set[str] = set()
    topics_by_scheme: dict[str, set[str]] = {}

    for c in chunks:
        cid = c.get("id", "?")
        if cid in seen_ids:
            problems.append(f"{cid}: duplicate chunk id")
        seen_ids.add(cid)
        text = c.get("text") or ""
        n = len(split_sentences(text))
        if not 1 <= n <= 3:
            problems.append(f"{cid}: {n} sentences (must be 1–3)")
        if not c.get("source_url"):
            problems.append(f"{cid}: missing source_url")
        elif not _allowed_source(c["source_url"]):
            problems.append(f"{cid}: source {c['source_url']} is not an allowed source")
        if not c.get("as_of"):
            problems.append(f"{cid}: missing as_of")
        if URL.search(text):
            problems.append(f"{cid}: URL inside chunk text")
        if RETURN_FIGURE.search(text):
            problems.append(f"{cid}: contains a return / performance figure")
        if BANNED_JUDGEMENT.search(text):
            problems.append(f"{cid}: contains a judgement word ({BANNED_JUDGEMENT.search(text).group(0)!r})")
        if c.get("scheme_id"):
            topics_by_scheme.setdefault(c["scheme_id"], set()).add(c.get("topic"))
            # Value rules re-checked on the finished corpus, not only while parsing (arch §15).
            topic = c.get("topic")
            if topic == "riskometer":
                m = re.search(r'"([^"]+)" risk', text)
                if not m or m.group(1) not in SEBI_RISK_LEVELS:
                    problems.append(f"{cid}: riskometer level is not one of SEBI's 6 levels")
            elif topic == "expense_ratio":
                m = re.search(r"is (\d+(?:\.\d+)?)% per annum", text)
                if not m or not 0 < float(m.group(1)) <= 3:
                    problems.append(f"{cid}: expense ratio missing or outside 0–3%")
            elif topic == "min_investment" and "SIP investments in" not in text:
                m = re.search(r"minimum SIP amount for .+? is ₹([\d,]+)\.", text)
                if not m or int(m.group(1).replace(",", "")) < 1:
                    problems.append(f"{cid}: minimum SIP missing or not a positive whole number")
            if c.get("source_url") not in (registry.BY_ID[c["scheme_id"]].url, HDFC_FACTSHEET_URL):
                problems.append(f"{cid}: scheme fact cites {c.get('source_url')}, not its own scheme page")
        elif c.get("topic") not in OFFICIAL_TOPICS:
            problems.append(f"{cid}: unknown official topic {c.get('topic')!r}")

    for s in registry.SCHEMES:
        missing = set(SCHEME_TOPICS) - topics_by_scheme.get(s.id, set())
        if missing:
            problems.append(f"{s.id}: missing topics {', '.join(sorted(missing))}")
    extra = set(topics_by_scheme) - set(registry.BY_ID)
    if extra:
        problems.append(f"chunks for unknown schemes: {', '.join(sorted(extra))}")
    if set(corpus.get("schemes") or {}) != set(registry.BY_ID):
        problems.append("corpus scheme list does not match the registry")
    return problems


# ---------------------------------------------------------------------------
# Atomic write and lock (GAP-04)
# ---------------------------------------------------------------------------

def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so readers never see a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class IngestLock:
    """Stops two ingestion runs at once. A lock older than 30 minutes is stale."""

    def __init__(self, path: Path = LOCK):
        self.path = path
        self.held = False

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    f.write(f"pid={os.getpid()} started={dt.datetime.now(IST).isoformat()}\n")
                self.held = True
                return self
            except FileExistsError:
                age = time.time() - self.path.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    self.path.unlink(missing_ok=True)
                    continue
                raise IngestError(f"another ingestion run is in progress ({self.path.name} exists; "
                                  "delete it if no run is active)") from None
        raise IngestError("could not acquire the ingestion lock")

    def __exit__(self, *exc):
        if self.held:
            self.path.unlink(missing_ok=True)
        return False


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def load_official_docs() -> tuple[list[dict], str]:
    data = json.loads(OFFICIAL_DOCS.read_text(encoding="utf-8"))
    reviewed = data["reviewed_on"]
    docs = [{**doc, "scheme_id": None, "scheme_name": None, "as_of": reviewed} for doc in data["docs"]]
    return docs, reviewed


def load_fetch_log() -> dict:
    try:
        return json.loads(FETCH_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def build(offline: bool = False, log=print) -> tuple[dict, dict[str, str], dict]:
    """Build the corpus in memory. Returns (corpus, new_snapshots, fetch_log).

    Raises IngestError for any problem; nothing is written here.
    """
    problems = registry.check_registry()
    if problems:
        raise IngestError("registry problems: " + "; ".join(problems))

    official, reviewed_on = load_official_docs()
    fetch_log = load_fetch_log()
    new_snapshots: dict[str, str] = {}
    sources: dict[str, dict] = {}
    chunks: list[dict] = []
    errors: list[str] = []
    fetched_now = today()

    for s in registry.SCHEMES:
        html, origin = None, None
        if not offline:
            try:
                html, origin = fetch(s.url), "live"
            except IngestError:
                raise
            except Exception as e:
                log(f"  {s.id}: live fetch failed ({e}); trying saved snapshot")
        if html is not None:
            try:
                d = parse_page(html)
                check_identity(s, d)
            except IngestError as e:
                log(f"  {s.id}: live page unusable ({e}); trying saved snapshot")
                html = None
        if html is None:
            snap = RAW / f"{s.id}.html"
            if not snap.exists():
                errors.append(f"{s.id}: no live page and no saved snapshot")
                continue
            html, origin = snap.read_text(encoding="utf-8"), "snapshot"
        try:
            d = parse_page(html)
            check_identity(s, d)
            as_of = fetched_now if origin == "live" else (fetch_log.get(s.id, {}).get("fetched_on"))
            if not as_of:
                raise IngestError("snapshot has no recorded fetch date in data/raw/fetched.json")
            chunks += scheme_chunks(s, d, as_of, reviewed_on)
        except IngestError as e:
            errors.append(f"{s.id}: {e}")
            continue
        if origin == "live":
            new_snapshots[s.id] = html
            fetch_log[s.id] = {"url": s.url, "fetched_on": fetched_now}
        sources[s.id] = {"url": s.url, "origin": origin, "fetched_on": as_of}
        log(f"  {s.id}: ok ({origin}, {as_of})")

    if errors:
        raise IngestError("; ".join(errors))

    chunks += official
    corpus = {
        "built_on": fetched_now,
        "factsheet_url": HDFC_FACTSHEET_URL,
        "official_reviewed_on": reviewed_on,
        "schemes": {
            s.id: {"name": s.name, "label": s.label, "url": s.url, "group": s.group,
                   "category": s.category, "isin": s.isin, "aliases": list(s.aliases),
                   "factsheet_url": HDFC_FACTSHEET_URL}
            for s in registry.SCHEMES
        },
        "sources": sources,
        "chunks": chunks,
    }
    problems = validate_corpus(corpus)
    if problems:
        raise IngestError("validation failed:\n    " + "\n    ".join(problems))
    return corpus, new_snapshots, fetch_log


def build_embeddings(corpus_path: Path | None = None, *, log=print) -> str:
    """Embed every chunk, save data/embeddings.npy + .json, and (re)build the Chroma
    collection (architecture §8.4). Returns "built", "up to date" or "skipped: <why>".

    Skips the 40-second model run when the saved vectors already match this corpus
    and model. Never fails ingestion: problems are reported and BM25 stays available.
    """
    from bolosip import config, embedder, vectorstore

    corpus_path = corpus_path or CORPUS
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    chunks = corpus["chunks"]
    sha = embedder.corpus_hash(corpus_path)
    model_name = config.SETTINGS.embed_model
    try:
        import chromadb  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return "skipped: the 'embed' extra is not installed (needs Python 3.10–3.14; see README)"

    vectors, meta = vectorstore.load_vectors()
    if (vectors is not None and meta.get("corpus_sha256") == sha and meta.get("model") == model_name
            and vectorstore.mismatch(vectors, meta, chunks) is None):     # damaged metadata → re-embed (ISS-024)
        # Still make sure the model is cached: queries need it even when the vectors don't
        # (a fresh clone or CI has the committed vectors but not the 550 MB model).
        if embedder.load(model_name, allow_download=True) is None:
            return f"skipped: vectors are up to date but {model_name} could not be loaded (no network?)"
        status = "up to date"
    else:
        model = embedder.load(model_name, allow_download=True)
        if model is None:
            return f"skipped: could not load {model_name} (no network on first run?)"
        log(f"Embedding {len(chunks)} chunks with {model_name} (about a minute on CPU)...")
        vectors = model.embed_documents([embedder.document_text(c) for c in chunks])
        meta = {
            "model": model_name,
            "doc_prefix": config.EMBED_DOC_PREFIX,
            "query_prefix": config.EMBED_QUERY_PREFIX,
            "embedded_text": "text + keywords",
            "dims": int(vectors.shape[1]),
            "count": int(vectors.shape[0]),
            "chunk_ids": [c["id"] for c in chunks],
            "corpus_sha256": sha,
            "built_on": today(),
        }
        vectorstore.save_vectors(vectors, meta)
        status = "built"
    vectorstore.reset_cache()
    store = vectorstore.build(vectors, chunks, meta)
    log(f"ChromaDB collection '{config.CHROMA_COLLECTION}': {store.count} vectors in "
        f"{config.SETTINGS.chroma_dir.relative_to(ROOT) if config.SETTINGS.chroma_dir.is_relative_to(ROOT) else config.SETTINGS.chroma_dir}")
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build data/corpus.json from the 27 HDFC scheme pages.")
    ap.add_argument("--offline", action="store_true", help="use saved snapshots only (no network)")
    ap.add_argument("--embed-only", action="store_true",
                    help="don't fetch; (re)build embeddings + ChromaDB for the existing corpus.json")
    ap.add_argument("--no-embed", action="store_true", help="skip the embedding step (used by tests)")
    args = ap.parse_args(argv)
    utf8_output()

    if args.embed_only:
        problems = validate_corpus(json.loads(CORPUS.read_text(encoding="utf-8")))
        if problems:
            print("NOT EMBEDDED: corpus.json fails validation; run python ingest.py first", file=sys.stderr)
            return 2
        status = build_embeddings()
        print(f"Embeddings: {status}")
        return 0 if not status.startswith("skipped") else 2

    try:
        with IngestLock():
            print(f"Building corpus ({'offline, snapshots only' if args.offline else 'live'}) "
                  f"for {len(registry.SCHEMES)} schemes")
            corpus, new_snapshots, fetch_log = build(offline=args.offline)
            RAW.mkdir(parents=True, exist_ok=True)
            for sid, html in new_snapshots.items():
                write_atomic(RAW / f"{sid}.html", html)
            if new_snapshots:
                write_atomic(FETCH_LOG, json.dumps(dict(sorted(fetch_log.items())), indent=2) + "\n")
            write_atomic(CORPUS, json.dumps(corpus, ensure_ascii=False, indent=2) + "\n")
    except IngestError as e:
        print(f"NOT WRITTEN: {e}", file=sys.stderr)
        return 2

    from_snapshot = [sid for sid, src in corpus["sources"].items() if src["origin"] == "snapshot"]
    print(f"Wrote {len(corpus['chunks'])} chunks for {len(corpus['schemes'])} schemes -> data/corpus.json")
    if not args.no_embed:
        try:
            print(f"Embeddings: {build_embeddings()}")
        except Exception as e:   # never fail ingestion because of embeddings
            print(f"Embeddings: skipped ({type(e).__name__}: {e})", file=sys.stderr)
    if from_snapshot:
        print(f"WARNING: {len(from_snapshot)} scheme(s) used saved snapshots: {', '.join(from_snapshot)}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
