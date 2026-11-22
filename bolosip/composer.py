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

from typing import Callable

from bolosip import config, registry
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
    return candidate if accept_rephrase(candidate, chunk) else text


def accept_rephrase(candidate: str | None, chunk: dict) -> bool:
    """Phase 8 output checks plug in here (numbers, URLs, advice). Until then: format only."""
    if not candidate or candidate.strip() == "NOT_IN_SOURCE":
        return False
    probe = make("answer", candidate, url=chunk["source_url"], source_name=chunk["source_name"],
                 as_of=chunk["as_of"])
    return probe.text == " ".join(candidate.split()) and not validate(probe)


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
