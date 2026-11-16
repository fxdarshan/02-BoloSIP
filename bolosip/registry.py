"""The 27 HDFC Mutual Fund schemes BoloSIP covers (problem statement §3.1).

This is the single source of truth for scheme IDs, their Groww page URLs
(the only URLs ingestion may fetch), display names, groups, categories,
expected ISINs and the aliases users may type.

Aliases are stored *normalised*: lowercase, "&" written as "and", hyphens as
spaces. An alias listed under more than one scheme is ambiguous on purpose
(e.g. "hdfc equity"); the resolver (Phase 3) must then ask which one is meant.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scheme:
    id: str
    name: str          # official short name, e.g. "HDFC Mid Cap Fund"
    url: str           # Groww scheme page: the only source fetched for it
    group: str         # Equity | Hybrid | Debt | FoF
    category: str      # as listed in problem statement §3.1
    isin: str          # expected ISIN of the Direct Growth plan (identity check)
    aliases: tuple[str, ...]

    @property
    def slug(self) -> str:
        """The page slug, e.g. "hdfc-mid-cap-fund-direct-growth"."""
        return self.url.rstrip("/").rsplit("/", 1)[-1]

    @property
    def label(self) -> str:
        """How the scheme is named in answers."""
        return f"{self.name} (Direct Growth)"


_G = "https://groww.in/mutual-funds/"

SCHEMES: tuple[Scheme, ...] = (
    # ---- Equity (16) -------------------------------------------------------
    Scheme("hdfc-large-cap", "HDFC Large Cap Fund", _G + "hdfc-large-cap-fund-direct-growth",
           "Equity", "Large Cap", "INF179K01YV8",
           ("hdfc large cap", "large cap", "largecap", "large cap fund", "hdfc top 100", "top 100")),
    Scheme("hdfc-mid-cap", "HDFC Mid Cap Fund", _G + "hdfc-mid-cap-fund-direct-growth",
           "Equity", "Mid Cap", "INF179K01XQ0",
           ("hdfc mid cap", "mid cap", "midcap", "mid cap fund", "mid cap opportunities",
            "hdfc mid cap opportunities")),
    Scheme("hdfc-small-cap", "HDFC Small Cap Fund", _G + "hdfc-small-cap-fund-direct-growth",
           "Equity", "Small Cap", "INF179KA1RW5",
           ("hdfc small cap", "small cap", "smallcap", "small cap fund")),
    Scheme("hdfc-large-and-mid-cap", "HDFC Large and Mid Cap Fund", _G + "hdfc-large-mid-cap-fund-direct-growth",
           "Equity", "Large & Mid Cap", "INF179KA1RQ7",
           ("hdfc large and mid cap", "large and mid cap", "large and midcap", "large mid cap",
            "large midcap", "large and mid cap fund")),
    Scheme("hdfc-multi-cap", "HDFC Multi Cap Fund", _G + "hdfc-multi-cap-fund-direct-growth",
           "Equity", "Multi Cap", "INF179KC1BS5",
           ("hdfc multi cap", "multi cap", "multicap", "multi cap fund", "multi")),
    Scheme("hdfc-flexi-cap", "HDFC Flexi Cap Fund", _G + "hdfc-equity-fund-direct-growth",
           "Equity", "Flexi Cap", "INF179K01UT0",
           ("hdfc flexi cap", "flexi cap", "flexicap", "flexi", "flexi cap fund",
            "hdfc equity fund", "hdfc equity")),
    Scheme("hdfc-focused", "HDFC Focused Fund", _G + "hdfc-focused-fund-direct-growth",
           "Equity", "Focused", "INF179K01VK7",
           ("hdfc focused", "focused", "focused fund", "focused 30", "hdfc focused 30")),
    Scheme("hdfc-nifty-50-index", "HDFC NIFTY 50 Index Fund", _G + "hdfc-nifty-50-index-fund-direct-growth",
           "Equity", "Index (Large Cap)", "INF179K01WM1",
           ("hdfc nifty 50 index", "nifty 50 index", "nifty 50 index fund", "nifty 50 fund",
            "nifty50", "nifty fifty", "large cap index", "index fund")),
    Scheme("hdfc-bse-sensex-index", "HDFC BSE Sensex Index Fund", _G + "hdfc-bse-sensex-index-fund-direct-growth",
           "Equity", "Index (Large Cap)", "INF179K01WN9",
           ("hdfc bse sensex index", "bse sensex index", "sensex index", "sensex index fund",
            "sensex fund", "bse sensex", "sensex", "large cap index", "index fund")),
    Scheme("hdfc-pharma-and-healthcare", "HDFC Pharma and Healthcare Fund",
           _G + "hdfc-pharma-and-healthcare-fund-direct-growth",
           "Equity", "Sectoral", "INF179KC1HO1",
           ("hdfc pharma and healthcare", "pharma and healthcare", "pharma", "pharma fund",
            "healthcare", "healthcare fund", "health care")),
    Scheme("hdfc-technology", "HDFC Technology Fund", _G + "hdfc-technology-fund-direct-growth",
           "Equity", "Sectoral", "INF179KC1HI3",
           ("hdfc technology", "technology", "technology fund", "tech fund", "tech")),
    Scheme("hdfc-transportation-and-logistics", "HDFC Transportation and Logistics Fund",
           _G + "hdfc-transportation-and-logistics-fund-direct-growth",
           "Equity", "Sectoral", "INF179KC1GU0",
           ("hdfc transportation and logistics", "transportation and logistics", "transportation",
            "transport", "logistics")),
    Scheme("hdfc-defence", "HDFC Defence Fund", _G + "hdfc-defence-fund-direct-growth",
           "Equity", "Thematic", "INF179KC1GI5",
           ("hdfc defence", "defence", "defense", "defence fund", "defense fund")),
    Scheme("hdfc-housing-opportunities", "HDFC Housing Opportunities Fund",
           _G + "hdfc-housing-opportunities-fund-direct-growth",
           "Equity", "Thematic", "INF179KC1AU3",
           ("hdfc housing opportunities", "housing opportunities", "housing", "housing fund")),
    Scheme("hdfc-business-cycle", "HDFC Business Cycle Fund", _G + "hdfc-business-cycle-fund-direct-growth",
           "Equity", "Thematic", "INF179KC1DY9",
           ("hdfc business cycle", "business cycle", "business cycle fund")),
    Scheme("hdfc-infrastructure", "HDFC Infrastructure Fund", _G + "hdfc-infrastructure-fund-direct-growth",
           "Equity", "Thematic", "INF179K01WQ2",
           ("hdfc infrastructure", "infrastructure", "infrastructure fund", "infra", "infra fund")),
    # ---- Hybrid (4) --------------------------------------------------------
    Scheme("hdfc-balanced-advantage", "HDFC Balanced Advantage Fund",
           _G + "hdfc-balanced-advantage-fund-direct-growth",
           "Hybrid", "Dynamic Asset Allocation", "INF179K01WA6",
           ("hdfc balanced advantage", "balanced advantage", "balanced advantage fund", "baf",
            "hdfc prudence", "prudence")),
    Scheme("hdfc-multi-asset-allocation", "HDFC Multi Asset Allocation Fund",
           _G + "hdfc-multi-asset-allocation-fund-direct-growth",
           "Hybrid", "Multi Asset Allocation", "INF179K01XW8",
           ("hdfc multi asset allocation", "multi asset allocation", "multi asset", "multiasset",
            "multi asset fund", "multi")),
    Scheme("hdfc-equity-savings", "HDFC Equity Savings Fund", _G + "hdfc-equity-savings-fund-direct-growth",
           "Hybrid", "Equity Savings", "INF179K01XT4",
           ("hdfc equity savings", "equity savings", "equity saving", "equity savings fund",
            "hdfc equity")),
    Scheme("hdfc-arbitrage", "HDFC Arbitrage Fund", _G + "hdfc-arbitrage-fund-direct-growth",
           "Hybrid", "Arbitrage", "INF179KA1KT6",
           ("hdfc arbitrage", "arbitrage", "arbitrage fund")),
    # ---- Debt (6) ----------------------------------------------------------
    Scheme("hdfc-overnight", "HDFC Overnight Fund", _G + "hdfc-overnight-fund-direct-growth",
           "Debt", "Overnight", "INF179KB1HT1",
           ("hdfc overnight", "overnight", "overnight fund")),
    Scheme("hdfc-liquid", "HDFC Liquid Fund", _G + "hdfc-liquid-fund-direct-growth",
           "Debt", "Liquid", "INF179KB1HP9",
           ("hdfc liquid", "liquid", "liquid fund")),
    Scheme("hdfc-money-market", "HDFC Money Market Fund", _G + "hdfc-money-market-fund-direct-growth",
           "Debt", "Money Market", "INF179KB1HU9",
           ("hdfc money market", "money market", "money market fund")),
    Scheme("hdfc-ultra-short-term", "HDFC Ultra Short Term Fund", _G + "hdfc-ultra-short-term-fund-direct-growth",
           "Debt", "Ultra Short Term", "INF179KB15Q6",
           ("hdfc ultra short term", "ultra short term", "ultra short", "ultra short term fund",
            "ultra short duration")),
    Scheme("hdfc-banking-and-psu-debt", "HDFC Banking and PSU Debt Fund",
           _G + "hdfc-banking-and-psu-debt-fund-direct-growth",
           "Debt", "Banking and PSU Debt", "INF179KA1IZ7",
           ("hdfc banking and psu debt", "banking and psu debt", "banking and psu", "banking psu",
            "psu debt", "banking and psu fund")),
    Scheme("hdfc-gilt", "HDFC Gilt Fund", _G + "hdfc-gilt-fund-direct-growth",
           "Debt", "Gilt", "INF179K01VS0",
           ("hdfc gilt", "gilt", "gilt fund")),
    # ---- Fund of Funds (1) -------------------------------------------------
    Scheme("hdfc-silver-etf-fof", "HDFC Silver ETF FoF", _G + "hdfc-silver-etf-fof-direct-growth",
           "FoF", "FoF – Silver", "INF179KC1DU7",
           ("hdfc silver etf fof", "silver etf fof", "silver etf", "silver fof", "silver",
            "silver fund")),
)

BY_ID: dict[str, Scheme] = {s.id: s for s in SCHEMES}
ALLOWED_URLS: frozenset[str] = frozenset(s.url for s in SCHEMES)
EXPECTED_COUNT = 27


def alias_index() -> dict[str, tuple[str, ...]]:
    """alias -> scheme IDs that use it (more than one ID means ambiguous)."""
    index: dict[str, list[str]] = {}
    for s in SCHEMES:
        for a in s.aliases:
            index.setdefault(a, []).append(s.id)
    return {a: tuple(ids) for a, ids in index.items()}


def check_registry() -> list[str]:
    """Structural problems with the registry (empty list if it is sound)."""
    problems = []
    if len(SCHEMES) != EXPECTED_COUNT:
        problems.append(f"expected {EXPECTED_COUNT} schemes, found {len(SCHEMES)}")
    for field in ("id", "url", "isin", "name"):
        values = [getattr(s, field) for s in SCHEMES]
        dupes = sorted({v for v in values if values.count(v) > 1})
        if dupes:
            problems.append(f"duplicate {field}: {', '.join(dupes)}")
    for s in SCHEMES:
        if not (s.url.startswith(_G + "hdfc-") and s.url.endswith("-direct-growth")):
            problems.append(f"{s.id}: URL is not a Groww HDFC Direct Growth page: {s.url}")
        if s.group not in ("Equity", "Hybrid", "Debt", "FoF"):
            problems.append(f"{s.id}: unknown group {s.group!r}")
        for a in s.aliases:
            if a != a.lower() or "&" in a or "-" in a or "  " in a or a != a.strip():
                problems.append(f"{s.id}: alias not normalised: {a!r}")
    return problems
