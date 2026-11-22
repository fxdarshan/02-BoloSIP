"""Topic names and the keyword lexicon shared by ingestion and retrieval.

One copy, used by ``ingest.py`` (to attach keywords to chunks) and by the
retriever in Phase 3 (to detect a question's topic). See architecture §5.2.
"""
from __future__ import annotations

# The 12 single-fact topics built for every scheme (architecture §5.2).
SCHEME_TOPICS = (
    "expense_ratio",
    "exit_load",
    "min_investment",
    "riskometer",
    "benchmark",
    "lock_in",
    "fund_manager",
    "category",
    "nav",
    "aum",
    "scheme_details",
    "stamp_duty",
)

# The 5 core facts checked for every scheme by acceptance criterion 1.
CORE_TOPICS = ("expense_ratio", "exit_load", "min_investment", "riskometer", "benchmark")

# Topics of the hand-curated official notes (data/official_docs.json).
OFFICIAL_TOPICS = (
    "statement",
    "capital_gains",
    "lock_in_general",
    "riskometer_general",
    "expense_ratio_general",
    "exit_load_general",
    "plans_general",
    "sip_general",
    "factsheet",
)

# Words people use for each scheme topic. Attached to chunks as `keywords`.
TOPIC_KEYWORDS = {
    "expense_ratio": "expense ratio ter total expense ratio cost costs charges charge fee fees annual expenses expence "
                     "management fee yearly fee running cost",
    "exit_load": "exit load redemption charge redeem early withdrawal penalty withdraw exit fee",
    "min_investment": "minimum sip amount min sip minimum investment lumpsum lump sum one time start investing smallest amount",
    "riskometer": "riskometer risk level risk classification risk category risk grade how risky",
    "benchmark": "benchmark index benchmark index tracks compared against tri total return index "
                 "track tracking follows measured against reference index",
    # No "elss" / "tax saving" here: those words belong to the official ELSS note, and
    # every scheme's lock-in fact already says "not an ELSS (tax-saving) scheme" in its text.
    "lock_in": "lock in lockin locked period stuck withdraw anytime holding period",
    "fund_manager": "fund manager fund managers managed by who manages manager",
    "category": "category type kind objective investment objective what is this scheme about",
    "nav": "nav net asset value unit price price per unit",
    "aum": "aum fund size assets under management corpus size",
    "scheme_details": "launch date inception launched isin registrar rta plan direct growth started",
    "stamp_duty": "stamp duty government duty duty charged duty on purchase tax on purchase levy on investing",
}

# High-precision phrases that name a scheme topic outright. Used only to break ties
# between neighbouring topics ("management fee" is an expense, not a fund manager);
# matched on normalised text (bolosip.schemes.normalise). Architecture §8.5.
TOPIC_PHRASES = {
    "expense_ratio": ("expense ratio", "ter", "management fee", "annual fee", "yearly fee", "annual charges",
                      "yearly charges", "running charges", "running cost"),
    "exit_load": ("exit load", "exit fee", "exit charge", "redemption fee", "redemption charge",
                  "withdrawal charge", "early redemption", "redeem early"),
    "min_investment": ("minimum sip", "min sip", "minimum investment", "minimum amount", "lump sum", "lumpsum",
                       "smallest amount", "least amount"),
    "riskometer": ("riskometer", "risk level", "risk grade", "risk category", "risk label", "how risky", "risk rating"),
    "benchmark": ("benchmark", "compared against", "compared with", "measured against", "track", "tracks",
                  "reference index"),
    "lock_in": ("lock in", "lockin", "locked", "stuck", "holding period", "withdraw anytime"),
    "fund_manager": ("fund manager", "fund managers", "who manages", "managed by", "who runs"),
    "category": ("objective", "invest in", "what kind", "what type", "category"),
    "nav": ("nav", "net asset value", "unit price", "price per unit"),
    "aum": ("aum", "fund size", "assets under management", "how big", "corpus size"),
    "scheme_details": ("isin", "launch date", "launched", "registrar", "rta", "inception"),
    "stamp_duty": ("stamp duty", "government duty", "duty charged", "duty on purchase"),
}

# How each scheme topic is named in replies ("You can ask separately about the exit load.").
TOPIC_LABELS = {
    "expense_ratio": "expense ratio",
    "exit_load": "exit load",
    "min_investment": "minimum investment",
    "riskometer": "riskometer level",
    "benchmark": "benchmark",
    "lock_in": "lock-in period",
    "fund_manager": "fund managers",
    "category": "category and objective",
    "nav": "NAV",
    "aum": "fund size (AUM)",
    "scheme_details": "launch date and ISIN",
    "stamp_duty": "stamp duty",
}

# Topics whose value differs between the Direct and Regular plans or the Growth and
# IDCW options (GAP-05). The corpus holds Direct Growth only, so these are never
# answered for another plan; the other topics are shared by every plan of a scheme.
VARIANT_TOPICS = ("expense_ratio", "nav", "aum", "scheme_details")

# SEBI's six riskometer levels (problem statement glossary).
SEBI_RISK_LEVELS = (
    "Low",
    "Low to Moderate",
    "Moderate",
    "Moderately High",
    "High",
    "Very High",
)
