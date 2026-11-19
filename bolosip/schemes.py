"""Scheme resolution: which of the 27 schemes does a message mean? (architecture §7)

The retriever can't tell schemes apart (same-topic chunks are 50–70% identical,
see Doc/retrieval-research.md), so the scheme is decided here, by names only:

    0. another fund house named, and HDFC not  -> other_amc  (GAP-01)
       a non-fund HDFC business named          -> non_fund   (SCH-17)
    1. alias matching, longest alias first     -> one / ambiguous / multiple
    2. nothing matched                         -> the thread's last scheme (follow-ups) or none

Pure functions, no I/O; aliases come from bolosip/registry.py.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from bolosip import registry
from bolosip.config import OTHER_AMC_NAMES
from bolosip.topics import SCHEME_TOPICS

_ZERO_WIDTH = re.compile(r"[​-‏⁠﻿]")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")

# HDFC group businesses that are not HDFC Mutual Fund schemes (edge case SCH-17).
NON_FUND_HDFC = (
    "hdfc bank", "hdfc life", "hdfc ergo", "hdfc securities", "hdfc sky", "hdfc credila",
    "hdfc capital", "hdfc pension", "hdfc sales", "hdfc credit card", "hdfc home loan",
    "hdfc fd", "hdfc fixed deposit", "hdfc share", "hdfc stock",
)


def normalise(text: str) -> str:
    """Lowercase; full-width -> normal (NFKC); zero-width removed; '&' -> 'and';
    hyphens and punctuation -> spaces; spaces collapsed."""
    t = unicodedata.normalize("NFKC", text)
    t = _ZERO_WIDTH.sub("", t).lower()
    t = t.replace("&", " and ").replace("’", "'").replace("'s ", " ")
    t = _NON_WORD.sub(" ", t)
    return " ".join(t.split())


def _contains(norm: str, phrase: str) -> bool:
    return f" {phrase} " in f" {norm} "


@dataclass(frozen=True)
class Resolution:
    """kind: one | ambiguous | multiple | other_amc | non_fund | none"""
    kind: str
    scheme_ids: tuple[str, ...] = ()
    via: str | None = None               # "message" or "context" (for kind == "one")
    matched: tuple[str, ...] = field(default=())   # aliases / names that matched

    @property
    def scheme_id(self) -> str | None:
        return self.scheme_ids[0] if self.kind == "one" else None

    @property
    def candidates(self) -> list[str]:
        """Display names for a clarifying question."""
        return [registry.BY_ID[i].name for i in self.scheme_ids]


# Aliases sorted longest first (by words, then characters) so "large and mid cap"
# is consumed before "large cap" and "mid cap" can match inside it.
_ALIAS_INDEX = registry.alias_index()
_ALIASES = sorted(_ALIAS_INDEX, key=lambda a: (-len(a.split()), -len(a)))
_OTHER_AMC = sorted({normalise(a) for a in OTHER_AMC_NAMES}, key=len, reverse=True)
_NON_FUND = tuple(normalise(n) for n in NON_FUND_HDFC)


# Weak aliases: words that are also everyday market, sector or commodity terms ("what is
# the Sensex today", "silver price", "housing loan"). They name a scheme only when the
# message also signals a fund question: HDFC, a fund word, or a fund-fact word.
WEAK_ALIASES = frozenset({
    "sensex", "bse sensex", "nifty50", "nifty fifty", "silver", "gilt", "liquid", "overnight",
    "money market", "arbitrage", "pharma", "healthcare", "health care", "technology", "tech",
    "transport", "transportation", "logistics", "defence", "defense", "housing", "infrastructure",
    "infra", "focused", "flexi", "multi", "prudence", "baf", "business cycle", "ultra short",
})
_FUND_SIGNAL = re.compile(
    r"\b(?:hdfc|fund|funds|scheme|schemes|etf|fof|nav|sip|sips|ter|aum|isin|rta|exit load|expense ratio|"
    r"riskometer|benchmark|lock in|lockin|fund manager|managed by|minimum|lump sum|lumpsum|stamp duty|"
    r"fund size|launch|launched|direct plan|direct growth)\b")


def has_fund_signal(text: str) -> bool:
    """True if a message reads like a question about a fund (HDFC, a fund word or a fund fact)."""
    return bool(_FUND_SIGNAL.search(normalise(text)))


def _match_aliases(norm: str) -> list[str]:
    """Non-overlapping alias matches, longest first. Weak aliases need a fund signal."""
    padded = f" {norm} "
    taken = [False] * len(padded)
    found = []
    fund_signal = bool(_FUND_SIGNAL.search(norm))
    for alias in _ALIASES:
        if alias in WEAK_ALIASES and not fund_signal:
            continue
        needle = f" {alias} "
        start = padded.find(needle)
        while start != -1:
            span = range(start + 1, start + len(needle) - 1)
            if not any(taken[i] for i in span):
                for i in span:
                    taken[i] = True
                found.append(alias)
            start = padded.find(needle, start + 1)
    return found


def resolve(text: str, last_scheme: str | None = None, topic: str | None = None) -> Resolution:
    """Decide which scheme(s) a message is about.

    ``last_scheme`` is the thread's previous scheme (follow-ups such as "what about its
    exit load?"). It is used only when no scheme is named and ``topic`` is a
    scheme-specific topic or unknown (None); never for general topics like "statement".
    """
    norm = normalise(text)

    # 0. Other fund houses and non-fund HDFC businesses.
    mentions_hdfc = _contains(norm, "hdfc")
    other = [a for a in _OTHER_AMC if _contains(norm, a)]
    if other and not mentions_hdfc:
        return Resolution("other_amc", matched=tuple(other))

    # 1. Aliases.
    matched = _match_aliases(norm)
    unique = {_ALIAS_INDEX[a][0] for a in matched if len(_ALIAS_INDEX[a]) == 1}
    groups = [set(_ALIAS_INDEX[a]) for a in matched if len(_ALIAS_INDEX[a]) > 1]

    if not matched:
        non_fund = [n for n in _NON_FUND if _contains(norm, n)]
        if non_fund:
            return Resolution("non_fund", matched=tuple(non_fund))
        named = _named_hdfc_scheme(norm)
        if named:
            return Resolution("not_covered", matched=(named,))
    if len(unique) == 1 and all(unique <= g for g in groups):
        return Resolution("one", tuple(unique), "message", tuple(matched))
    if len(unique) > 1 or (unique and groups):
        ids = set(unique).union(*groups) if groups else set(unique)
        return Resolution("multiple", _ordered(ids), None, tuple(matched))
    if groups:
        return Resolution("ambiguous", _ordered(set().union(*groups)), None, tuple(matched))

    # 2. Nothing named: a follow-up uses the thread's last scheme.
    if last_scheme in registry.BY_ID and (topic is None or topic in SCHEME_TOPICS):
        return Resolution("one", (last_scheme,), "context")
    return Resolution("none")


# An HDFC scheme named but not one of the 27 (edge case SCH-18), e.g. "HDFC Gold ETF Fund
# of Fund", "HDFC ELSS Tax Saver". Only called when no alias matched.
_SCHEME_WORD = r"(?:fund|funds|etf|fof|scheme|saver|plan)"
_GENERIC = frozenset("mutual fund funds direct growth plan scheme schemes the a an any my mf amc regular idcw "
                     "of s".split())
_NAMED_SCHEME = re.compile(rf"\bhdfc((?: [a-z0-9]+){{1,5}}?) {_SCHEME_WORD}\b|\bhdfc (?:elss|tax saver)\b")


def _named_hdfc_scheme(norm: str) -> str | None:
    m = _NAMED_SCHEME.search(norm)
    if not m:
        return None
    words = (m.group(1) or " elss").split()
    return m.group(0) if any(w not in _GENERIC for w in words) else None


def _ordered(ids: set[str]) -> tuple[str, ...]:
    """Registry order, so clarifying questions list schemes consistently."""
    return tuple(s.id for s in registry.SCHEMES if s.id in ids)
