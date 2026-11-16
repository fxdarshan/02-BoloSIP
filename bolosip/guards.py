"""Pre-retrieval guards: personal data, advisory intent and performance questions.

These run before anything is retrieved or stored, so the assistant never answers an
advisory question and never persists personal identifiers.
"""
from __future__ import annotations

import re

# ---- Personal data -----------------------------------------------------------------

PII_PATTERNS = {
    "PAN": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.I),
    "Aadhaar": re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b"),
    "email address": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone number": re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"),
    "OTP": re.compile(r"\b(?:otp|one[\s-]?time[\s-]?password)\b\D{0,15}\d{4,8}\b", re.I),
    "account / folio number": re.compile(
        r"\b(?:a/?c|account|acct|folio)\s*(?:no\.?|number|#)?\s*[:\-]?\s*[A-Z0-9/]{6,20}\b", re.I),
    "long number": re.compile(r"(?<!\d)\d{9,18}(?!\d)"),
}


def find_pii(text: str) -> list[str]:
    """Return the kinds of personal data found in text (empty list if none)."""
    found = []
    for kind, pat in PII_PATTERNS.items():
        m = pat.search(text)
        if not m:
            continue
        # "account number" pattern also matches plain words like "account statement"
        if kind == "account / folio number" and not re.search(r"\d", m.group(0)):
            continue
        found.append(kind)
    # The long-number rule is a catch-all; don't double report.
    if "long number" in found and len(found) > 1:
        found.remove("long number")
    return found


def redact(text: str) -> str:
    for pat in PII_PATTERNS.values():
        text = pat.sub(lambda m: "[redacted]" if re.search(r"\d|@", m.group(0)) else m.group(0), text)
    return text


# ---- Advisory / opinion questions ---------------------------------------------------

ADVISORY_PATTERNS = [
    r"\bshould i\b", r"\bshall i\b", r"\bshould we\b", r"\bis it (?:a )?(?:good|wise|safe|right|worth)\b",
    r"\bworth (?:it|investing|buying)\b", r"\b(?:good|bad|right|best|safe|smart) (?:time|idea|choice|option|investment|fund|scheme)s?\b",
    r"\bwhich (?:one |fund |scheme |of (?:these|them) )?(?:is |would be )?(?:better|best|good|safer)\b",
    r"\bbetter (?:than|fund|option|choice)\b", r"\bbest\b", r"\brecommend", r"\bsuggest", r"\badvi[cs]e\b",
    r"\b(?:vs\.?|versus)\b", r"\bcompare\b", r"\bcomparison\b",
    r"\bbuy\b", r"\bsell\b", r"\bswitch (?:to|from)\b", r"\bexit (?:now|the fund)\b",
    r"\bwill (?:it|the fund|nav|this)\b.*\b(?:go up|rise|grow|fall|perform|give)\b", r"\bpredict", r"\bforecast",
    r"\bhow much (?:should|can) i invest\b", r"\ballocat", r"\bmy portfolio\b", r"\bguarantee",
    r"\bsafe to invest\b", r"\bgood for (?:me|beginners|long term|retirement)\b", r"\binvest in this\b",
]
_ADVISORY = re.compile("|".join(ADVISORY_PATTERNS), re.I)


def is_advisory(text: str) -> bool:
    return bool(_ADVISORY.search(text))


# ---- Performance / returns questions -------------------------------------------------

_PERFORMANCE = re.compile(
    r"\breturns?\b|\bperform(?:ance|ed|ing)?\b|\bcagr\b|\bxirr\b|\byield\b|\bgrowth rate\b|"
    r"\bhow much (?:did|has|will|would)\b|\bgain(?:ed|s)? (?:in|over|last)\b|\bmade money\b|"
    r"\b(?:\d+|one|three|five|ten)[\s-]?(?:y|yr|yrs|year|years)\b.*\b(?:return|growth|gain)\b|"
    r"\bcalculat|\bsip calculator\b|\bif i (?:had )?invest",
    re.I,
)
# "capital gains statement" is a document request, not a performance question.
_NOT_PERFORMANCE = re.compile(r"capital gains?\b.*\b(statement|report)|\btax\b.*\bstatement", re.I)


def is_performance(text: str) -> bool:
    return bool(_PERFORMANCE.search(text)) and not _NOT_PERFORMANCE.search(text)
