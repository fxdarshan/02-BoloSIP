"""Phase 4 reply scoring, shared by the evaluation gate (eval/run.py) and tests.

`check_reply(r, reply, expect)` compares a pipeline `Reply` with a case's `expect`
block and returns a list of problems (empty = correct). It also enforces AC 2 / AC 3
for every reply: format (formatter.validate) and an allowed citation.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bolosip import config, registry
from bolosip.formatter import Reply, validate
from bolosip.retriever import Retriever

GROWW_URLS = frozenset(s.url for s in registry.SCHEMES)
FIGURE = re.compile(r"\d")


def citation_ok(reply: Reply) -> bool:
    """AC 3: the one link is a scheme page or an allowed official domain."""
    if reply.source is None:
        return reply.kind in ("clarify", "help")
    url = reply.source.url
    if url in GROWW_URLS:
        return True
    host = urlparse(url).hostname or ""
    return url.startswith("https://") and any(host == d or host.endswith("." + d) for d in config.OFFICIAL_DOMAINS)


def answered_chunk(r: Retriever, reply: Reply) -> dict | None:
    """The chunk an answer was taken from (extractive text, maybe with a prefix/suffix)."""
    if reply.kind != "answer":
        return None
    for c in r.chunks:
        if c["text"] in reply.text and c["source_url"] == reply.source.url:
            return c
    return None


def check_reply(r: Retriever, reply: Reply, expect: dict) -> list[str]:
    problems = [f"format: {p}" for p in validate(reply)]
    if not citation_ok(reply):
        problems.append(f"citation not allowed: {reply.source.url if reply.source else None}")
    kind = expect.get("kind")
    if kind is None:                              # guard negative: anything but that guard's kind
        return problems
    if reply.kind != kind:
        return problems + [f"kind {reply.kind} != {kind}"]
    if expect.get("scheme_id") and reply.scheme_id != expect["scheme_id"]:
        problems.append(f"scheme {reply.scheme_id} != {expect['scheme_id']}")
    if kind == "clarify" and expect.get("candidates"):
        names = {registry.BY_ID[i].name for i in expect["candidates"]}
        if set(reply.candidates or ()) != names:
            problems.append(f"candidates {reply.candidates} != {sorted(names)}")
    if kind == "answer":
        chunk = answered_chunk(r, reply)
        if "topic" in expect:
            if chunk is None or chunk["topic"] != expect["topic"] or \
                    (chunk["scheme_id"] or None) != (expect.get("scheme_id") or None):
                problems.append(f"answered {chunk['id'] if chunk else None}, expected "
                                f"{expect.get('scheme_id') or 'official'}:{expect['topic']}")
        for value in expect.get("contains", []):
            if value not in reply.text:
                problems.append(f"missing value {value!r}")
        if expect.get("source_url") and reply.source.url != expect["source_url"]:
            problems.append(f"source {reply.source.url} != {expect['source_url']}")
        if expect.get("prefix") and not reply.text.startswith(expect["prefix"]):
            problems.append(f"missing prefix {expect['prefix']!r}")
    if expect.get("contains_any") and not any(s in reply.text for s in expect["contains_any"]):
        problems.append(f"none of {expect['contains_any']} in the text")
    if kind == "performance" and FIGURE.search(reply.text):
        problems.append("figure in a performance reply")
    return problems
