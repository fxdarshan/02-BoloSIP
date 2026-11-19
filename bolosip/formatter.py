"""The `Reply` object, and formatting + validation of every reply (architecture §6.2, §10).

Every reply except `clarify` and `help` states something and so must carry:
1–3 sentences, exactly one link (the `source`, never a URL inside the text) and the
footer "Last updated from sources: <DD Mon YYYY>". `clarify` and `help` state no
fact: no link, no footer.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from bolosip.textutil import URL, split_sentences

KINDS = ("answer", "refusal", "performance", "privacy", "clarify", "help", "not_found")
LINKLESS = ("clarify", "help")
MAX_SENTENCES = 3
MAX_CANDIDATES = 5
FOOTER_PREFIX = "Last updated from sources: "
_DATE = re.compile(r"^\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}$")


@dataclass(frozen=True)
class Source:
    url: str
    name: str


@dataclass(frozen=True)
class Reply:
    kind: str
    text: str
    source: Source | None = None
    footer: str | None = None
    scheme_id: str | None = None
    candidates: tuple[str, ...] | None = None    # clarify: scheme names; help: example questions

    def to_dict(self) -> dict:
        d = asdict(self)
        d["candidates"] = list(self.candidates) if self.candidates is not None else None
        return d

    def render(self) -> str:
        """Plain-text form for the command line."""
        lines = [self.text]
        if self.candidates:
            lines += [f"  • {c}" for c in self.candidates]
        if self.source:
            lines.append(f"Source: {self.source.url}")
        if self.footer:
            lines.append(self.footer)
        return "\n".join(lines)


def footer(as_of: str) -> str:
    return f"{FOOTER_PREFIX}{as_of}"


def clean_text(text: str) -> str:
    """Remove URLs from the body and keep at most 3 sentences (FMT-01–06)."""
    # Drop the URL but keep punctuation glued to its end: "(https://x/a)." -> "()."
    text = URL.sub(lambda m: re.search(r"[).,;:!?]*$", m.group(0)).group(0), text)
    text = re.sub(r"\(\s*\)", "", text)                # "()" left behind by a removed URL
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)       # "page ." -> "page."
    sentences = split_sentences(text)[:MAX_SENTENCES]
    return " ".join(sentences).strip()


def make(kind: str, text: str, *, url: str | None = None, source_name: str | None = None,
         as_of: str | None = None, scheme_id: str | None = None,
         candidates: list[str] | tuple[str, ...] | None = None) -> Reply:
    """Build a formatted reply. Linked kinds get their source and footer attached."""
    if kind not in KINDS:
        raise ValueError(f"unknown reply kind {kind!r}")
    if kind in LINKLESS:
        return Reply(kind, " ".join(text.split()), scheme_id=scheme_id,
                     candidates=tuple(candidates or ()))
    return Reply(kind, clean_text(text), Source(url or "", source_name or ""),
                 footer(as_of) if as_of else None, scheme_id, None)


def validate(reply: Reply) -> list[str]:
    """Problems with a reply; an empty list means it is valid (arch §10 step 5)."""
    problems = []
    if reply.kind not in KINDS:
        return [f"unknown kind {reply.kind!r}"]
    if not reply.text.strip():
        problems.append("empty text")
    if URL.search(reply.text):
        problems.append("URL inside the text")
    if reply.kind in LINKLESS:
        if reply.source is not None or reply.footer is not None:
            problems.append(f"{reply.kind} must have no link and no footer")
        if reply.kind == "clarify" and len(reply.candidates or ()) > MAX_CANDIDATES:
            problems.append(f"more than {MAX_CANDIDATES} candidates")
        return problems
    n = len(split_sentences(reply.text))
    if not 1 <= n <= MAX_SENTENCES:
        problems.append(f"{n} sentences (need 1–{MAX_SENTENCES})")
    if reply.source is None or not re.match(r"^https://\S+$", reply.source.url or ""):
        problems.append("missing or invalid source link")
    if not reply.footer or not reply.footer.startswith(FOOTER_PREFIX) or \
            not _DATE.match(reply.footer[len(FOOTER_PREFIX):]):
        problems.append(f"bad footer {reply.footer!r}")
    if reply.candidates:
        problems.append("candidates on a linked reply")
    return problems
