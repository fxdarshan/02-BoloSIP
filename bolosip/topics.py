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
    "expense_ratio": "expense ratio ter total expense ratio cost costs charges charge fee fees annual expenses expence",
    "exit_load": "exit load redemption charge redeem early withdrawal penalty withdraw exit fee",
    "min_investment": "minimum sip amount min sip minimum investment lumpsum lump sum one time start investing smallest amount",
    "riskometer": "riskometer risk level risk classification risk category risk grade how risky",
    "benchmark": "benchmark index benchmark index tracks compared against tri total return index",
    "lock_in": "lock in lock-in lockin locked period lock in period elss tax saving",
    "fund_manager": "fund manager fund managers managed by who manages manager",
    "category": "category type kind objective investment objective what is this scheme about",
    "nav": "nav net asset value unit price price per unit",
    "aum": "aum fund size assets under management corpus size",
    "scheme_details": "launch date inception launched isin registrar rta plan direct growth started",
    "stamp_duty": "stamp duty",
}

# SEBI's six riskometer levels (problem statement glossary).
SEBI_RISK_LEVELS = (
    "Low",
    "Low to Moderate",
    "Moderate",
    "Moderately High",
    "High",
    "Very High",
)
