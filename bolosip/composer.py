"""Answer text and the fixed replies (architecture §9.1, §10.1; problem statement §4.2).

Extractive mode (the default, and the only mode until Phase 8): the answer is the top
chunk's text, unchanged. Chunks were written at ingest time to read as finished
answers. `compose()` takes an optional `rephrase` hook so Phase 8 can plug in the Groq
LLM without changing callers; whatever the hook returns is ignored unless it passes
the output checks, so extractive text is always the fallback.

Fixed replies never state a scheme fact; each carries one official link and the date
that link was last reviewed.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Callable

from bolosip import config, guards, registry
from bolosip.formatter import Reply, make, validate
from bolosip.topics import TOPIC_LABELS

Rephrase = Callable[[str, str], "str | None"]


def compose(question: str, chunk: dict, rephrase: Rephrase | None = None) -> str:
    """Answer text for a chunk. Phase 8 passes `rephrase`; any failure keeps the chunk text."""
    text = chunk["text"]
    if rephrase is None:
        return text
    try:
        candidate = rephrase(question, text)
    except Exception:
        return text
    if candidate:
        candidate = candidate.translate(_STRAIGHT_QUOTES)
    return candidate if accept_rephrase(candidate, chunk) else text


def accept_rephrase(candidate: str | None, chunk: dict) -> bool:
    """Phase 8 output checks (architecture §9.2). Any failure keeps the extractive text."""
    return rejection_reason(candidate, chunk) is None


def rejection_reason(candidate: str | None, chunk: dict) -> str | None:
    """Why an LLM rewording can't be used, or None if it passes every check."""
    if not candidate or not candidate.strip():
        return "empty"
    if "NOT_IN_SOURCE" in candidate:
        return "not in source"
    if _URLISH.search(candidate):
        return "url"
    if guards.is_advisory(candidate) or _ADVICE_OUT.search(candidate):
        return "advice words"
    src = chunk["text"]
    nums, dates = numbers_and_dates(candidate)
    src_nums, src_dates = numbers_and_dates(src)
    if not nums <= src_nums:
        return "number not in source: " + ", ".join(sorted(nums - src_nums))
    if not dates <= src_dates:
        return "date not in source"
    # Nothing that matters may be dropped either: every number and date, quoted levels such
    # as "Very High", the plan name and words like "blocked" (live run, 24 Nov 2026).
    if not src_nums <= nums:
        return "dropped a number: " + ", ".join(sorted(src_nums - nums))
    if not src_dates <= dates:
        return "dropped the date"
    flat = candidate.translate(_STRAIGHT_QUOTES).lower()
    src_flat = src.translate(_STRAIGHT_QUOTES).lower()
    for phrase in _MUST_KEEP + tuple(_QUOTED.findall(src_flat)):
        if phrase in src_flat and phrase not in flat:
            return f"dropped {phrase!r}"
    low, src_low = candidate.lower(), src.lower()
    for s in registry.SCHEMES:
        if s.name.lower() in low and s.name.lower() not in src_low:
            return f"names another scheme: {s.name}"
    probe = make("answer", candidate, url=chunk["source_url"], source_name=chunk["source_name"],
                 as_of=chunk["as_of"])
    if probe.text != " ".join(candidate.split()) or validate(probe):
        return "format"
    return None


# --- number and date normalising for the output check (GAP-06) -------------------

_URLISH = re.compile(r"https?://|www\.|\b[a-z0-9-]+\.(?:com|in|org|net|gov|co)\b", re.I)
_STRAIGHT_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
_QUOTED = re.compile(r'"[^"]{1,40}"')
_MUST_KEEP = ("direct growth", "blocked", "suspended", "not accepting", "no exit load", "nil", "not applicable")
# Advice phrased as a statement to the user (the question guard looks for "should I ...").
_ADVICE_OUT = re.compile(
    r"\b(?:you|investors?)\s+(?:should|must|ought to|could consider|may want to|might want to|need to)\b"
    r"|\b(?:i|we)\s+(?:recommend|suggest|advise)\b|\brecommended\b|\bconsider (?:investing|buying|adding)\b"
    r"|\bworth (?:investing|buying|it)\b|\b(?:good|great|safe|smart|ideal|right) (?:choice|option|pick|bet|investment)\b"
    r"|\bsuitable for you\b|\bgo for it\b", re.I)
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/]+" + _MON + r"[\s\-/,]+(\d{4})\b", re.I)
_DATE_MDY = re.compile(r"\b" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_CURRENCY = re.compile(r"₹|\bRs\.?(?=\s?\d)|\bINR\b", re.I)
_WORDS = {w: str(i) for i, w in enumerate(
    ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"), 1)}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.I)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _month(name: str) -> int:
    return _MONTHS[name.lower()[:3]]


def numbers_and_dates(text: str) -> tuple[set[str], set[tuple[int, int, int]]]:
    """Normalised numbers and (year, month, day) dates in a text.

    "₹1,00,687.07", "Rs 100687.07" and "100,687.070" all give "100687.07"; "one year"
    gives "1"; "0.730%" gives "0.73"; "12 Nov 2026", "12-Nov-2026", "Nov 12, 2026" and
    "2026-11-12" give the same date. Dates are taken out before numbers are read."""
    dates: set[tuple[int, int, int]] = set()

    def take_dmy(m):
        dates.add((int(m.group(3)), _month(m.group(2)), int(m.group(1))))
        return " "

    def take_mdy(m):
        dates.add((int(m.group(3)), _month(m.group(1)), int(m.group(2))))
        return " "

    def take_iso(m):
        dates.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
        return " "

    t = _DATE_DMY.sub(take_dmy, text)
    t = _DATE_MDY.sub(take_mdy, t)
    t = _DATE_ISO.sub(take_iso, t)
    t = _CURRENCY.sub(" ", t)
    t = _NUMBER_WORD.sub(lambda m: _WORDS[m.group(1).lower()], t)
    nums = set()
    for raw in _NUMBER.findall(t):
        value = raw.replace(",", "").rstrip(".")
        try:
            d = Decimal(value)
        except InvalidOperation:
            continue
        s = format(d, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        nums.add(s.lstrip("0") or "0" if "." not in s else s)
    return nums, dates


def answer(question: str, chunk: dict, *, prefix: str = "", suffix: str = "",
           rephrase: Rephrase | None = None) -> Reply:
    """A factual answer from one chunk: its text, its source link, its date."""
    text = compose(question, chunk, rephrase)
    if prefix:
        text = prefix + text
    if suffix and len(_sentences(text)) < 3:
        text = f"{text} {suffix}"
    return make("answer", text, url=chunk["source_url"], source_name=chunk["source_name"],
                as_of=chunk["as_of"], scheme_id=chunk.get("scheme_id"))


def _sentences(text: str) -> list[str]:
    from bolosip.textutil import split_sentences
    return split_sentences(text)


# ---------------------------------------------------------------------------
# Fixed replies
# ---------------------------------------------------------------------------

def refusal(meta: dict) -> Reply:
    """Rule 2: advice, opinion, comparison or recommendation."""
    return make(
        "refusal",
        "I can only share factual information about HDFC Mutual Fund schemes, so I can't advise "
        "whether you should invest or which scheme to choose. For guidance on choosing mutual funds, "
        "see AMFI's investor education resources.",
        url=config.AMFI_INVESTOR_URL, source_name="AMFI – Investor Corner",
        as_of=meta["official_reviewed_on"])


def performance(meta: dict, scheme_id: str | None = None) -> Reply:
    """Rule 3: returns or performance. No figures, only the factsheet link."""
    if scheme_id:
        s = meta["schemes"][scheme_id]
        text = (f"I don't share returns or performance figures. You can see the historical performance "
                f"of {s['name']} in HDFC Mutual Fund's official monthly factsheet.")
        url = s.get("factsheet_url") or config.HDFC_FACTSHEET_URL
    else:
        text = ("I don't share returns or performance figures. You can see each scheme's historical "
                "performance in HDFC Mutual Fund's official monthly factsheets.")
        url = config.HDFC_FACTSHEET_URL
    return make("performance", text, url=url, source_name="HDFC Mutual Fund – Factsheets",
                as_of=meta["official_reviewed_on"], scheme_id=scheme_id)


def privacy(meta: dict) -> Reply:
    """Rule 1: personal data. Never echoes the value back (CMP-04)."""
    return make(
        "privacy",
        "Please don't share personal details such as PAN, Aadhaar, account or folio numbers, phone "
        "numbers or OTPs: BoloSIP doesn't need them and doesn't store them. I can answer factual "
        "questions about HDFC Mutual Fund schemes without any personal information.",
        url=config.SEBI_INVESTOR_URL, source_name="SEBI – Investor website",
        as_of=meta["official_reviewed_on"])


def clarify(scheme_ids: tuple[str, ...] | list[str], *, several_named: bool = False) -> Reply:
    """Rule 4 with candidates: the name matches several schemes, or several were named."""
    names = [registry.BY_ID[i].name for i in scheme_ids]
    shown = names[:5]
    more = len(names) - len(shown)
    if several_named:
        text = "I can answer for one scheme at a time. Which one do you mean?"
    else:
        text = "That name matches more than one scheme. Which one do you mean?"
    if more > 0:
        text += f" {more} more schemes also match, so naming the scheme fully narrows it down."
    return make("clarify", text, candidates=shown)


def ask_for_scheme() -> Reply:
    """Rule 4 with no scheme named at all: ask for one, with 3 examples."""
    return make("clarify", "Which scheme do you mean? Please name one of the 27 HDFC Mutual Fund "
                           "schemes, for example:", candidates=EXAMPLE_SCHEMES)


EXAMPLE_SCHEMES = ("HDFC Mid Cap Fund", "HDFC Liquid Fund", "HDFC Flexi Cap Fund")


def help_reply() -> Reply:
    """GAP-02: greetings, questions about BoloSIP, messages with no meaningful words."""
    return make("help", config.WELCOME_TEXT + " Try one of these:", candidates=config.EXAMPLE_QUESTIONS)


def not_found(meta: dict, official_chunk: dict | None = None) -> Reply:
    """Rule 5: not in the sources. Links the closest official page, else AMFI."""
    text = ("I couldn't find that in BoloSIP's sources, so I won't guess. I can answer factual "
            "questions about 27 HDFC Mutual Fund schemes, and the closest official page is linked below.")
    if official_chunk:
        return make("not_found", text, url=official_chunk["source_url"],
                    source_name=official_chunk["source_name"], as_of=official_chunk["as_of"])
    return make("not_found", text, url=config.AMFI_INVESTOR_URL, source_name="AMFI – Investor Corner",
                as_of=meta["official_reviewed_on"])


def other_amc(meta: dict) -> Reply:
    """GAP-01: another fund house is named."""
    return make("not_found",
                "BoloSIP only covers 27 schemes of HDFC Mutual Fund, so I can't answer about other fund "
                "houses. AMFI's investor page has general information about mutual funds.",
                url=config.AMFI_INVESTOR_URL, source_name="AMFI – Investor Corner",
                as_of=meta["official_reviewed_on"])


def non_fund(meta: dict) -> Reply:
    """SCH-17: an HDFC group business that is not a mutual fund scheme."""
    return make("not_found",
                "BoloSIP only covers 27 schemes of HDFC Mutual Fund, not other HDFC group businesses "
                "such as HDFC Bank or HDFC Life. AMFI's investor page has general information about "
                "mutual funds.",
                url=config.AMFI_INVESTOR_URL, source_name="AMFI – Investor Corner",
                as_of=meta["official_reviewed_on"])


def not_covered(meta: dict, named: str, elss_chunk: dict | None = None) -> Reply:
    """SCH-18: an HDFC scheme outside the 27. For an ELSS scheme, link the ELSS rule."""
    name = display_name(named)
    if elss_chunk is not None:
        return make("not_found",
                    f"{name} is not one of the 27 HDFC Mutual Fund schemes BoloSIP covers, and none of "
                    "the 27 is an ELSS (tax-saving) scheme. The general ELSS lock-in rule is on the "
                    "linked page.",
                    url=elss_chunk["source_url"], source_name=elss_chunk["source_name"],
                    as_of=elss_chunk["as_of"])
    return make("not_found",
                f"{name} is not one of the 27 HDFC Mutual Fund schemes BoloSIP covers, so I can't answer "
                "about it. HDFC Mutual Fund's factsheets cover all of its schemes.",
                url=config.HDFC_FACTSHEET_URL, source_name="HDFC Mutual Fund – Factsheets",
                as_of=meta["official_reviewed_on"])


def direct_growth_only(meta: dict, scheme_id: str, topic: str, variant: str) -> Reply:
    """GAP-05: a Regular plan or IDCW value was asked for a topic that differs by plan."""
    s = meta["schemes"][scheme_id]
    src = meta["sources"][scheme_id]
    what = TOPIC_LABELS.get(topic, "details")
    return make("not_found",
                f"BoloSIP covers only the Direct Growth plan of {s['name']}, so I can't give the "
                f"{variant} {what}. The linked scheme page shows the Direct Growth details.",
                url=s["url"], source_name=f"{s['name']} – Groww scheme page", as_of=src["fetched_on"],
                scheme_id=scheme_id)


_UPPER = {"hdfc", "etf", "fof", "elss", "psu", "bse", "nifty", "it", "amc"}


def display_name(named: str) -> str:
    """'hdfc gold etf fund' -> 'HDFC Gold ETF Fund'."""
    return " ".join(w.upper() if w in _UPPER else w.capitalize() for w in named.split())
