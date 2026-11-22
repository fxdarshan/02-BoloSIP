"""Question suggestions: typing suggestions, follow-up chips and fallback chips (UI).

The web page receives this small index once, in `/api/config`, and matches it in the
browser as the user types, so suggestions are instant and cost the server nothing.
Every question this module can produce is checked by `tests/test_suggest.py` to get a
correct, cited answer, so a suggestion never leads to "not found" (chatbot-flow-design:
"suggest the bot's actual capabilities, not generic options").
"""
from __future__ import annotations

from bolosip import config, registry
from bolosip.topics import TOPIC_LABELS, TOPIC_PHRASES

# One question template per scheme topic, in the order they are offered. The first
# five are the core facts (problem statement AC 1).
TOPIC_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("expense_ratio", "What is the expense ratio of {name}?"),
    ("exit_load", "What is the exit load of {name}?"),
    ("min_investment", "What is the minimum SIP for {name}?"),
    ("riskometer", "What is the riskometer level of {name}?"),
    ("benchmark", "What is the benchmark of {name}?"),
    ("fund_manager", "Who manages {name}?"),
    ("nav", "What is the NAV of {name}?"),
    ("aum", "What is the fund size of {name}?"),
    ("lock_in", "Is there a lock-in period for {name}?"),
    ("scheme_details", "When was {name} launched?"),
    ("category", "What does {name} invest in?"),
    ("stamp_duty", "Is there stamp duty on {name}?"),
)

# Extra words people type for a topic (matched as word prefixes in the browser).
_EXTRA_KEYS = {
    "expense_ratio": "ter cost fees charges",
    "exit_load": "redemption withdrawal penalty",
    "min_investment": "sip minimum lumpsum lump amount",
    "riskometer": "risk risky",
    "benchmark": "index tracks",
    "fund_manager": "manager managers manages",
    "nav": "price unit",
    "aum": "aum size assets",
    "lock_in": "lockin locked",
    "scheme_details": "launch inception isin",
    "category": "category objective type",
    "stamp_duty": "stamp duty",
}

# General questions (official notes), each phrased the way the evaluation sets show works.
GENERAL_QUESTIONS: tuple[str, ...] = tuple(config.EXAMPLE_QUESTIONS) + (
    "Where can I get a capital gains statement?",
    "What is a Consolidated Account Statement?",
    "What is an exit load?",
    "What is a riskometer?",
    "What is TER in mutual funds?",
    "What is the difference between a direct plan and a regular plan?",
    "What is a SIP?",
    "Where can I find the HDFC factsheet?",
)


_working: dict[int, list[str]] = {}


def working_general(retriever) -> list[str]:
    """General questions this retriever answers (the BM25 fallback misses some
    definitions, ISS-015). Checked once per retriever, then cached."""
    key = id(retriever)
    if key not in _working:
        from bolosip import pipeline
        _working[key] = [q for q in GENERAL_QUESTIONS
                         if pipeline.handle(q, {}, retriever=retriever)[0].kind == "answer"]
    return _working[key]


def suggestion_index(retriever=None) -> dict:
    """The compact index the web page matches against as the user types. With a
    retriever, general questions it can't answer are left out."""
    topics = []
    for topic, template in TOPIC_TEMPLATES:
        keys = " ".join([TOPIC_LABELS[topic], *TOPIC_PHRASES.get(topic, ()), _EXTRA_KEYS.get(topic, "")])
        topics.append({"id": topic, "label": TOPIC_LABELS[topic].capitalize() if topic != "nav" else "NAV",
                       "template": template, "keys": " ".join(sorted(set(keys.lower().split())))})
    schemes = [{"id": s.id, "name": s.name,
                "keys": " ".join(sorted(set(" ".join((s.name, *s.aliases)).lower().replace("&", "and").split())))}
               for s in registry.SCHEMES]
    general = working_general(retriever) if retriever is not None else list(GENERAL_QUESTIONS)
    return {"schemes": schemes, "topics": topics, "general": general, "core": 5}


def all_questions() -> list[tuple[str, str | None, str | None]]:
    """Every question the UI can suggest: (question, scheme_id, topic). For tests."""
    out = [(t.format(name=s.name), s.id, topic) for s in registry.SCHEMES for topic, t in TOPIC_TEMPLATES]
    out += [(q, None, None) for q in GENERAL_QUESTIONS]
    return out
