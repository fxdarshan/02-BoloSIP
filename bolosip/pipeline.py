"""One message in, one `Reply` out (architecture §6; problem statement §4.2 rules 1–6).

    handle(text, ctx) -> (Reply, new_ctx)

`ctx` is the thread's context, today only {"last_scheme": <scheme id or None>}. The
function is pure apart from reading the shared retriever: it never stores anything
(the API stores the redacted message and the reply, Phase 5).

Order, first match wins:
  1. personal data          -> privacy      (SEBI link)
  2. advice / opinion       -> refusal      (AMFI link)
  3. returns / performance  -> performance  (factsheet link, no figures)
     greeting / about BoloSIP / no meaningful words -> help (GAP-02)
  resolve the scheme: other fund house, non-fund HDFC, HDFC scheme not covered -> not_found
  4. several schemes match, or a scheme-specific question names none -> clarify
  5. retrieval below the confidence threshold -> not_found (closest official link)
  6. otherwise -> answer (top chunk, its link, its date)
"""
from __future__ import annotations

import re

from bolosip import composer, guards, registry
from bolosip.formatter import Reply, validate
from bolosip.retriever import Retriever, get_retriever, phrase_topics, tokenize
from bolosip.schemes import has_fund_signal, normalise, resolve
from bolosip.topics import SCHEME_TOPICS, TOPIC_LABELS, VARIANT_TOPICS

# --- Help (GAP-02) -----------------------------------------------------------
_SMALL_TALK = frozenset(
    "hi hii hiii hello hey hola namaste namaskar yo thanks thank thx ty you ok okay okk cool great nice "
    "good morning afternoon evening night bye goodbye see later welcome yes no yeah yep nope sure fine "
    "hmm hm help bolosip bot there again much lot so very all".split())
_ABOUT_BOT = re.compile(
    r"\b(?:what can (?:you|i) (?:do|ask)|what do you do|who (?:made|built|created|are) you|what are you|"
    r"how (?:do|does) (?:you|this|bolosip|it) work|what is bolosip|what can you answer|"
    r"what (?:questions|things) can i ask|how (?:can|do) i use (?:you|this|bolosip))\b")

# --- Follow-ups and plan variants --------------------------------------------
_REFERS_BACK = re.compile(r"\b(?:its|it s|it)\b|\b(?:this|that|the same|same|the) (?:fund|scheme|one)\b")
_VARIANT = re.compile(r"\b(regular|idcw|dividend|payout|reinvestment|reinvest)\b")
_DEFINITION = re.compile(
    r"\b(?:what (?:is|are) (?:a|an)|what s (?:a|an)|define|definition of|meaning of|what is meant by|"
    r"what does .{1,40} (?:mean|include|cover)|explain (?:what|the term))\b|\bmeaning\b")
# Things none of the 27 schemes is: asking "which scheme?" about them would mislead (OOC-34).
_NOT_A_SCHEME = re.compile(
    r"\b(?:gold|savings account|current account|salary account|credit card|debit card|loan|loans|emi|"
    r"insurance|policy|fixed deposit|fd|demat|crypto|bitcoin|share price|stock price|ipo)\b")
_ELSS = re.compile(r"\b(?:elss|tax saver|tax saving (?:fund|scheme|mutual fund)s?|80c)\b")
# Words that don't ask for anything: with only these and a scheme name, the user wants
# to know what the scheme is (SCH-22, CTX-03) -> its category / objective fact.
_GENERIC = frozenset(
    "hdfc fund funds scheme schemes mutual mf direct growth plan option and also what about how is the "
    "a an of for tell me details info information know more on please".split())


def handle(text: str, ctx: dict | None = None, *, retriever: Retriever | None = None,
           rephrase=None) -> tuple[Reply, dict]:
    """Apply rules 1–6 to one message. Returns the reply and the updated thread context."""
    r = retriever or get_retriever()
    ctx = dict(ctx or {})
    last = ctx.get("last_scheme") if ctx.get("last_scheme") in registry.BY_ID else None
    meta = r.meta
    norm = normalise(text)

    # Rules 1–3: the guards, in order. They don't change the thread's scheme (CTX-05).
    g = guards.check(text)
    if g.kind == "privacy":
        return composer.privacy(meta), ctx
    if g.kind == "refusal":
        return composer.refusal(meta), ctx
    if g.kind == "performance":
        res = resolve(text)
        return composer.performance(meta, res.scheme_id if res.kind == "one" else None), ctx

    if _is_help(text, norm):
        return composer.help_reply(), ctx

    reply, new_last = _answer_or_not(r, text, norm, last, rephrase)
    if new_last:
        ctx["last_scheme"] = new_last
    if validate(reply):              # never expected for extractive text; never send a bad reply
        reply = composer.not_found(meta)
    return reply, ctx


def _is_help(text: str, norm: str) -> bool:
    if _ABOUT_BOT.search(norm):
        return True
    return not [t for t in tokenize(norm) if t not in _SMALL_TALK]


def _answer_or_not(r: Retriever, text: str, norm: str, last: str | None, rephrase):
    meta = r.meta
    res = resolve(text)

    # Step 0 of resolution: not an HDFC Mutual Fund scheme of the 27.
    if res.kind == "other_amc":
        return composer.other_amc(meta), None
    if res.kind == "non_fund":
        return composer.non_fund(meta), None
    if res.kind == "not_covered":
        elss = r.by_id.get("official:elss_lockin") if _ELSS.search(norm) else None
        return composer.not_covered(meta, res.matched[0], elss), None

    # Rule 4: several schemes.
    if res.kind in ("ambiguous", "multiple"):
        return composer.clarify(res.scheme_ids, several_named=res.kind == "multiple"), None

    named = phrase_topics(text)
    refers_back = bool(_REFERS_BACK.search(norm))
    definition = bool(_DEFINITION.search(norm)) and not refers_back

    # ELSS questions with no covered scheme named: the official ELSS note, which says none of
    # the 27 schemes is an ELSS (problem statement §3.1).
    if res.kind == "none" and _ELSS.search(norm):
        chunk = r.by_id["official:elss_lockin"]
        return composer.answer(text, chunk, rephrase=rephrase), None

    scheme_id = res.scheme_id
    via_context = False
    if scheme_id is None:
        # A follow-up ("what about its exit load?") uses the thread's scheme, but a general
        # question ("how do I download my statement?") never does (CTX-10).
        hits_all = r.search(text)
        top_topic = hits_all[0].topic if r.is_confident(hits_all) else None
        if definition:
            topic = "definition"                      # never a follow-up: "what is a riskometer?"
        elif named or refers_back:
            topic = None                              # "what about its exit load?", "exit load?"
        else:
            topic = top_topic
        res_ctx = resolve(text, last, topic)
        if res_ctx.kind == "one":
            scheme_id, via_context = res_ctx.scheme_id, True
        elif refers_back and (named or top_topic in SCHEME_TOPICS or top_topic is None):
            return composer.ask_for_scheme(), None            # CTX-02: "its exit load?" in a new thread

    # GAP-05: a Regular plan / IDCW value. Shared topics are answered for Direct Growth,
    # labelled; plan-specific topics (or no clear topic) are not.
    variant = _VARIANT.search(norm)
    if scheme_id and variant:
        shared = sorted(t for t in named if t not in VARIANT_TOPICS)
        if shared and not (named & set(VARIANT_TOPICS)):
            chunk = r.by_id[f"{scheme_id}:{shared[0]}"]
            return composer.answer(text, chunk, prefix="For the Direct Growth plan: ", rephrase=rephrase), scheme_id
        topic = min(named & set(VARIANT_TOPICS), default="details")
        word = {"regular": "Regular plan's", "idcw": "IDCW option's", "dividend": "IDCW (dividend) option's",
                "payout": "IDCW payout option's"}.get(variant.group(1), "other plan's")
        return composer.direct_growth_only(meta, scheme_id, topic, word), scheme_id

    # ELSS asked about a covered scheme: its lock-in fact says it is not an ELSS scheme.
    if scheme_id and _ELSS.search(norm):
        return composer.answer(text, r.by_id[f"{scheme_id}:lock_in"], rephrase=rephrase), scheme_id

    # A scheme name and nothing else ("HDFC Mid Cap", "and small cap?"): what the scheme is.
    if scheme_id and not via_context and not named and _only_names(norm, res.matched):
        return composer.answer(text, r.by_id[f"{scheme_id}:category"], rephrase=rephrase), scheme_id

    hits = r.search(text, scheme_id, k=len(r.candidate_rows(scheme_id)))
    # A scheme is known and the question names one of its topics outright ("its exit load",
    # "its aum"): if the search also ranks that scheme's fact for that topic first among the
    # scheme's facts, the two signals agree and that fact is the answer, even for a terse
    # question that scores under the bar, and even if a general definition of the term
    # scores higher (RET-04, CTX-01). Definition questions keep the normal path.
    own = next((h for h in hits if h.scheme_id == scheme_id), None) if scheme_id and named else None
    if own is not None and own.topic in named and not definition:
        top = own
    elif not r.is_confident(hits, scheme_id):
        return composer.not_found(meta, _closest_official(r, text)), scheme_id
    else:
        top = hits[0]

    # Rule 4: a scheme-specific fact but no scheme named. Ask which one, if it reads like a
    # fund question; otherwise it is simply not covered ("what is the money market").
    if scheme_id is None and top.scheme_id is not None:
        if (has_fund_signal(text) or named) and not _NOT_A_SCHEME.search(norm):
            return composer.ask_for_scheme(), None
        return composer.not_found(meta, _closest_official(r, text)), None

    # RET-02: two topics asked at once -> answer one, and say so.
    suffix = ""
    # "category" is left out: its phrases ("invest in", "what type") are too loose to mean
    # the user asked about it ("government duty when I invest in X" is one question).
    others = [t for t in named if t != top.topic and t in TOPIC_LABELS and t != "category"]
    if top.scheme_id and others:
        suffix = f"You can ask separately about the {TOPIC_LABELS[sorted(others)[0]]}."
    return composer.answer(text, top.chunk, suffix=suffix, rephrase=rephrase), scheme_id


def _only_names(norm: str, matched: tuple[str, ...]) -> bool:
    rest = f" {norm} "
    for alias in matched:
        rest = rest.replace(f" {alias} ", " ")
    return not [w for w in rest.split() if w not in _GENERIC]


def _closest_official(r: Retriever, text: str) -> dict | None:
    """The most relevant official note, if it is relevant at all (arch §10.1)."""
    hits = [h for h in r.search(text, None, k=len(r.chunks)) if h.scheme_id is None]
    if hits and hits[0].score >= r.min_score(scheme_named=True):
        return hits[0].chunk
    return None
