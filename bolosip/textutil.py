"""Small text helpers shared by ingestion, the formatter (Phase 4) and tests."""
from __future__ import annotations

import re

# Abbreviations that end with a period but don't end a sentence.
_ABBREVIATIONS = ("rs.", "e.g.", "i.e.", "approx.", "no.", "nos.", "vs.", "etc.",
                  "mr.", "ms.", "mrs.", "dr.", "st.", "ltd.", "pvt.", "inc.", "co.")

_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z₹\"'(\[])")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences.

    Doesn't split inside decimals ("0.73%"), Indian amounts ("₹1,00,687.07")
    or after common abbreviations ("Rs. 100", "e.g. ELSS").
    """
    text = " ".join(text.split())
    if not text:
        return []
    pieces = _SPLIT.split(text)
    sentences: list[str] = []
    for piece in pieces:
        if sentences and sentences[-1].lower().endswith(_ABBREVIATIONS):
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)
    return sentences


# A percentage close to a returns word, in either order (ingest validation, CMP rules).
_RETURN_WORDS = r"(?:returns?|returned|cagr|xirr|annuali[sz]ed|gained|grew|growth of)"
RETURN_FIGURE = re.compile(
    rf"\d+(?:\.\d+)?\s?%[^.]{{0,40}}\b{_RETURN_WORDS}\b"
    rf"|\b(?:{_RETURN_WORDS}|[1-9]0?y)\b[^.]{{0,40}}\d+(?:\.\d+)?\s?%",
    re.IGNORECASE,
)

# Judgement words that must never appear in a fact (edge case CMP-01).
BANNED_JUDGEMENT = re.compile(
    r"\b(?:good|best|cheap|cheaper|cheapest|attractive|excellent|great|safe|safest|"
    r"recommended|ideal|top[- ]performing|outperform\w*|superior)\b",
    re.IGNORECASE,
)

URL = re.compile(r"https?://\S+", re.IGNORECASE)
