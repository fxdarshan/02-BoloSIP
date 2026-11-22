"""Pre-retrieval guards: personal data, advice / opinion, and returns questions.

These run before anything is retrieved, stored or sent to an LLM (architecture
§6, §11), in this order:

    1. personal data  -> "privacy"     (never retrieved, never stored unredacted)
    2. advice/opinion -> "refusal"
    3. returns        -> "performance" (factsheet link only, no figures)

Use ``check(text)`` for the ordered decision; the individual functions are for
tests and for checking LLM output (Phase 8). All functions are pure and fast:
every pattern is linear-time on the 500-character input limit.

Guiding rule (problem statement §1): when unsure, refuse. A factual question
refused costs a little; advice answered or personal data stored is a failure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_I = re.IGNORECASE

# ---------------------------------------------------------------------------
# 1. Personal data
# ---------------------------------------------------------------------------

# Order matters only for reporting: specific kinds first, the catch-all last.
PII_PATTERNS: dict[str, re.Pattern] = {
    # Plain PAN in any case; a spaced / dashed PAN only in capitals (so "since 2020 a" never matches).
    "PAN": re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b|\b[A-Z]{5}[\s-]\d{4}[\s-][A-Z]\b"),
    "Aadhaar": re.compile(
        r"(?<!\d)\d{4}[\s-]\d{4}[\s-]\d{4}(?:[\s-]\d{4})?(?!\d)"      # 4-4-4 (Aadhaar) / 4-4-4-4 (VID)
        r"|\b[X*]{4}[\s-]?[X*]{4}[\s-]?\d{4}\b", _I),                # masked: XXXX XXXX 1234
    # "aadhaar ... 4567": the keyword makes even a partial number personal data.
    "Aadhaar (partial)": re.compile(r"\baadhaa?r\b\D{0,20}?(\d{4}(?:[\s-]?\d{4}){0,3})(?!\d)", _I),
    "email address": re.compile(
        # (?<![\w.+-]) makes each match start only at the beginning of a token: linear time.
        r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"
        r"|(?<![\w.+-])[\w.+-]+\s*(?:\(at\)|\[at\]|\sat\s)\s*[\w-]+\s*(?:\(dot\)|\[dot\]|\sdot\s)\s*[a-z]{2,6}\b", _I),
    "phone number": re.compile(
        r"(?<![\d.])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?![\d.])"   # mobile
        r"|(?<![\d.])[6-9](?:[\s-]?\d){9}(?![\d.])"                       # mobile in any grouping: 99 88 77 66 55
        r"|(?<![\d.])0\d{2,4}[\s-]\d{3,4}[\s-]\d{4}(?![\d.])"),         # landline with STD code
    "OTP": re.compile(
        r"\b(?:otp|one[\s-]?time[\s-]?password|verification\s+code|security\s+code)\b\D{0,20}\d{4,8}\b", _I),
    "IFSC": re.compile(r"\b[A-Z]{4}0(?=[A-Z0-9]{6}\b)(?=[A-Z]*\d)[A-Z0-9]{6}\b", _I),
    "account / folio number": re.compile(
        r"\b(?:a/c|ac|account|acct|folio|bank\s+account)\s*(?:no\.?|number|num|#)?\s*[:.\-]?\s*\d[\d/\-]{4,}", _I),
    "long number": re.compile(r"(?<![\d.,])\d{9,18}(?![\d.,])"),
}

# Public identifiers that look like personal data but aren't: scheme ISINs
# (INF...) and toll-free 1800 numbers (e.g. HDFC MF's 1800-3010-6767).
_PUBLIC_ID = re.compile(r"\bINF[0-9A-Z]{9}\b|(?<!\d)1800[\s-]?\d{3,4}[\s-]?\d{4}(?!\d)", _I)


def find_pii(text: str) -> list[str]:
    """Kinds of personal data in ``text`` (never the values). Empty if none."""
    scrubbed = _PUBLIC_ID.sub(" ", text)
    found = [kind for kind, pat in PII_PATTERNS.items() if pat.search(scrubbed)]
    if "long number" in found and len(found) > 1:      # catch-all: don't double-report
        found.remove("long number")
    if "Aadhaar" in found and "Aadhaar (partial)" in found:
        found.remove("Aadhaar (partial)")
    return found


def redact(text: str) -> str:
    """Replace every personal-data value with "[redacted]"; keep the rest readable."""
    protected: dict[str, str] = {}

    def _protect(m: re.Match) -> str:
        key = f"\x00{len(protected)}\x00"
        protected[key] = m.group(0)
        return key

    def _redact_groups(m: re.Match) -> str:
        # Patterns with a capture group only hide the group (keep "aadhaar ending").
        if m.re.groups:
            start, end = m.span(1)
            s0 = m.start()
            return m.group(0)[: start - s0] + "[redacted]" + m.group(0)[end - s0:]
        return "[redacted]"

    out = _PUBLIC_ID.sub(_protect, text)
    for pat in PII_PATTERNS.values():
        out = pat.sub(_redact_groups, out)
    for key, value in protected.items():
        out = out.replace(key, value)
    return re.sub(r"(?:\[redacted\][\s-]*){2,}", "[redacted] ", out).strip()


# ---------------------------------------------------------------------------
# 2. Advice and opinion
# ---------------------------------------------------------------------------

_COST_WORDS = r"(?:expense ratio|ter|exit load|fees?|charges?|costs?|stamp duty|nav|aum|fund size)"
_JUDGEMENT = r"(?:too\s+)?(?:high|low|reasonable|expensive|cheap|fair|ok|okay|acceptable|competitive|justified)"

ADVISORY_PATTERNS = [
    # direct requests for a decision
    r"\bshould\s+(?:i|we)\b", r"\bshall\s+(?:i|we)\b", r"\bcan\s+i\s+invest\s+in\s+this\b",
    r"\b(?:is|are)\s+(?:it|this|that|they)\s+(?:a\s+)?(?:good|wise|safe|right|worth|smart|bad)\b",
    r"\bworth\s+(?:it|investing|buying)\b",
    r"\b(?:good|bad|right|best|safe|smart|ideal|wise)\s+(?:time|idea|choice|option|investment|fund|scheme|pick|"
    r"move|bet|decision|buy)s?\b",
    r"\b(?:would|will|do|did)\s+you\s+(?:put|invest|buy|like|prefer|choose|pick|trust)\b",
    r"\b(?:over|under)[\s-]?valued\b", r"\b(?:double|triple)\s+(?:my\s+|your\s+|the\s+)?(?:money|investment)\b",
    r"\bbest\b(?!\s+(?:way|method|place|time\s+to\s+(?:call|contact)))",
    r"\btop\s+(?!100\b)(?:\d+\s+)?(?:funds?|schemes?|picks?|performers?|performing)\b",
    r"\b(?:highest|lowest|top|best|worst)[\s-](?:returning|performing|rated|return)\b",
    r"\bwhich\s+(?:hdfc\s+)?(?:one|fund|scheme|plan|option)s?\b[^?.]{0,60}\b(?:better|best|most|least|highest|lowest|"
    r"safer|safest|good|cheaper|cheapest|lower|higher|more|less|should|recommend)\b",
    r"\bwhich\s+(?:is|would\s+be)\s+(?:better|best|good|safer)\b",
    r"\bbetter\s+(?:than|fund|option|choice|investment)\b",
    r"\brecommend\w*\b", r"\bsuggest\w*\b", r"\badvi[cs]e\b", r"\badvis[oe]r\b",
    # "compared against / with / to" is how people ask for a benchmark ("which index is it
    # compared against?"); comparing two schemes is still refused, or clarified as several schemes.
    r"\b(?:vs\.?|versus)\b", r"\bcompar(?:e|ing|ison)\b", r"\bcompared\b(?!\s+(?:against|with|to)\b)",
    r"\bwhich\s+one\b",
    # transactions and portfolio decisions
    # "when I sell units of X within 30 days" is an exit-load question, not a sell decision.
    r"\bbuy\b", r"\bsell\b(?!\s+(?:the\s+|my\s+|some\s+|all\s+)?units\s+(?:of|in|within|before|after|from)\b)",
    r"\bswitch\s+(?:to|from|my)\b", r"\bexit\s+(?:now|the\s+fund|my)\b",
    # "allocation" is advice except in scheme names / objectives ("Multi Asset Allocation",
    # "dynamic allocation between sectors").
    r"\bhow\s+much\s+(?:should|can|must)\s+i\s+invest\b",
    r"(?<!asset\s)(?<!dynamic\s)\ballocat\w*\b(?!\s+(?:fund|between\s+various))", r"\bmy\s+portfolio\b",
    r"\b(?:pick|choose)\s+(?:one|a\s+fund|for\s+me|between|the\s+best)\b",
    # suitability, safety, loss
    r"\bsafe\s+to\s+invest\b", r"\b(?:is|are)\s+[^?.]{0,60}\b(?:safe|safer|safest|risk[\s-]?free)\b",
    r"\bsuit(?:able|s)\b", r"\bgood\s+for\s+(?:me|beginners|long[\s-]term|retirement|"
    r"tax|kids|children|my)\b",
    r"\bfor\s+my\s+(?:child|children|kid|kids|son|daughter|retirement|goal|wife|husband|family|parents|wedding|house)\b",
    r"\b(?:can|will|could|might)\s+i\s+lose\b",
    r"\blose\s+(?:my\s+)?money\b(?!\s+to\s+(?:an?\s+|the\s+)?(?:exit|redemption))",
    # "guaranteed returns?" is advice; "securities guaranteed by GoI" (a gilt objective) is not.
    r"\bguarantee\w*\s+(?:returns?|profits?|income|gains?|growth)\b",
    r"\b(?:returns?|profits?|income)\s+(?:are\s+|is\s+)?guaranteed\b",
    r"\b(?:is|are)\s+(?:it|this|they|the\s+[\w\s]{1,30}?)\s+guaranteed\b",
    r"\b(?:too\s+)?risky\s+for\s+(?:me|us|beginners)\b", r"\bis\s+(?:it|this)\s+(?:too\s+)?risky\b",
    # predictions
    r"\bwill\s+(?:it|the\s+fund|the\s+nav|nav|this|the\s+scheme|[\w\s]{1,30}?)\s+(?:go\s+up|go\s+down|rise|fall|"
    r"grow|perform|give|beat|outperform|crash|recover)\b",
    r"\bpredict\w*\b", r"\bforecast\w*\b", r"\boutlook\b", r"\bfuture\s+(?:returns?|performance|nav)\b",
    # opinions about a value, ratings, other people's views
    rf"\b{_COST_WORDS}\b[^?.]{{0,40}}\b{_JUDGEMENT}\b(?!\s+risk)",
    rf"\b(?:is|are)\s+(?:a\s+|an\s+|the\s+)?{_JUDGEMENT}\s+{_COST_WORDS}\b",
    r"\b(?:what\s+do\s+you\s+think|your\s+(?:view|opinion|take|pick)|in\s+your\s+opinion)\b",
    r"\b(?:experts?|analysts?|people)\s+(?:say|think|recommend|suggest|rate)\b",
    r"\b(?:groww|star|morningstar|value\s+research|crisil|vro)(?:'s|’s)?\s+ratings?\b", r"\bhow\s+is\s+it\s+rated\b",
]
_ADVISORY = re.compile("|".join(f"(?:{p})" for p in ADVISORY_PATTERNS), _I)


def is_advisory(text: str) -> bool:
    return bool(_ADVISORY.search(text))


# ---------------------------------------------------------------------------
# 3. Returns and performance
# ---------------------------------------------------------------------------

_PERFORMANCE = re.compile(
    r"\breturns?\b|\breturned\b|\bperform(?:ance|ed|ing|s)?\b|\bcagr\b|\bxirr\b|\byields?\b|\bytm\b"
    r"|\bgrowth\s+rate\b|\bhow\s+much\s+(?:did|has|have|will|would)\b|\b(?:made|make|making)\s+money\b"
    r"|\bgain(?:ed|s)?\s+(?:in|over|last|this|since)\b|\bprofit\w*\b"
    r"|\bhow\s+(?:did|has|have|is)\s+(?:it|the\s+fund|this|[\w\s&]{1,40}?)\s+(?:do|done|doing|grow\w*|gr[eo]wn?|"
    r"fare[ds]?|faring)\b"
    r"|\bannuali[sz]ed\b|\bworth\s+(?:today|now)\b|\bpast\s+(?:returns?|performance|record)\b|\btrack\s+record\b"
    r"|\b(?:sip|return|lumpsum|lump\s+sum|investment|mutual\s+fund)\s+calculat\w*"
    r"|\bcalculate\s+(?:my\s+)?(?:returns?|gains?|profit|maturity|corpus|value)\b"
    r"|\bif\s+i\s+(?:had\s+)?invest(?:ed)?\s+(?:₹|rs\.?|inr)?\s?\d"
    r"|\bwhat\s+will\s+[^?]{0,30}\bbecome\b|\bwould\s+have\s+become\b"
    r"|\bnav\s+(?:on|history|in\s+\d{4}|as\s+of|last\s+(?:year|month|week)|trend|chart)\b|\bhistorical\s+nav\b"
    r"|\b52[\s-]?week\b|\ball[\s-]time\s+(?:high|low)\b",
    _I,
)
# Not performance: document requests, giving back units, and index names.
_NOT_PERFORMANCE = re.compile(
    r"\bcapital\s+gains?\b[^?.]{0,30}\b(?:statement|report)\b|\btax\b[^?.]{0,30}\bstatement\b"
    r"|\breturn\s+(?:my\s+|the\s+)?units\b|\btotal\s+return\s+index\b|\btri\b"
    r"|\b(?:income\s+)?tax\s+returns?\b|\bitr\b",
    _I,
)


def is_performance(text: str) -> bool:
    if not _PERFORMANCE.search(text):
        return False
    # Remove the harmless phrases and look again, so "Total Return Index ... 3 year returns" still counts.
    return bool(_PERFORMANCE.search(_NOT_PERFORMANCE.sub(" ", text)))


# ---------------------------------------------------------------------------
# Ordered decision (architecture §6, rules 1–3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GuardResult:
    kind: str | None              # "privacy" | "refusal" | "performance" | None (continue to retrieval)
    pii: tuple[str, ...] = ()     # kinds of personal data found (privacy only)


def check(text: str) -> GuardResult:
    """Apply the guards in order; the first that matches decides."""
    pii = find_pii(text)
    if pii:
        return GuardResult("privacy", tuple(pii))
    if is_advisory(text):
        return GuardResult("refusal")
    if is_performance(text):
        return GuardResult("performance")
    return GuardResult(None)
