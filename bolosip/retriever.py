"""Retrieval: which fact answers the question? (architecture §8)

The scheme is decided first by the resolver (bolosip/schemes.py); this module only
searches the **candidates**: that scheme's 12 facts + the 10 official notes, or all
chunks when no scheme is known. It never returns another scheme's fact.

Two backends behind one interface:

* dense  - local nomic embeddings (bolosip/embedder.py) + ChromaDB (bolosip/vectorstore.py).
           Default whenever the `embed` extra is installed and the vectors match corpus.json.
* bm25   - standard-library keyword search over `text + keywords`. Always available.

BOLOSIP_RETRIEVER = auto (dense if possible, else bm25) | embed (require dense) | bm25.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from bolosip import config, embedder as embedder_mod, vectorstore
from bolosip.schemes import normalise
from bolosip.topics import TOPIC_PHRASES

log = logging.getLogger("bolosip.retriever")

_STOP = frozenset(
    "a an the of for to in on is are was be it its this that what which who how do does did i my me can could "
    "would should will there any by with at from as and or about tell please".split())


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]


def phrase_topics(query: str) -> set[str]:
    """Scheme topics named outright by a high-precision phrase (topics.TOPIC_PHRASES)."""
    padded = f" {normalise(query)} "
    return {t for t, phrases in TOPIC_PHRASES.items() if any(f" {p} " in padded for p in phrases)}


@dataclass(frozen=True)
class Hit:
    chunk: dict
    score: float
    backend: str

    @property
    def topic(self) -> str:
        return self.chunk["topic"]

    @property
    def scheme_id(self) -> str | None:
        return self.chunk["scheme_id"]


class BM25:
    def __init__(self, docs: list[str], k1: float = config.BM25_K1, b: float = config.BM25_B):
        self.k1, self.b = k1, b
        self.toks = [tokenize(d) for d in docs]
        self.lens = [len(t) for t in self.toks]
        self.avg = sum(self.lens) / max(len(self.lens), 1)
        n = len(docs)
        df = Counter(w for t in self.toks for w in set(t))
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.tf = [Counter(t) for t in self.toks]

    def score(self, query: str, rows: list[int]) -> list[tuple[int, float]]:
        q = tokenize(query)
        out = []
        for i in rows:
            tf, s = self.tf[i], 0.0
            norm = self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg)
            for w in q:
                f = tf.get(w)
                if f:
                    s += self.idf[w] * f * (self.k1 + 1) / (f + norm)
            out.append((i, s))
        return out


class Retriever:
    def __init__(self, corpus_path: Path | None = None, mode: str | None = None, *,
                 embedder=None, store=None):
        """`embedder` / `store` can be injected (tests use pure-Python stubs)."""
        self.corpus_path = Path(corpus_path or config.SETTINGS.corpus_path)
        corpus = json.loads(self.corpus_path.read_text(encoding="utf-8"))
        self.chunks: list[dict] = corpus["chunks"]
        # Corpus metadata used by the reply builders (Phase 4): scheme names and factsheet
        # links, per-scheme fetch dates, and the date the official notes were reviewed.
        self.meta = {k: v for k, v in corpus.items() if k != "chunks"}
        self.by_id = {c["id"]: c for c in self.chunks}
        self.row = {c["id"]: i for i, c in enumerate(self.chunks)}
        self._official_rows = [i for i, c in enumerate(self.chunks) if not c["scheme_id"]]
        self._rows_by_scheme: dict[str, list[int]] = {}
        for i, c in enumerate(self.chunks):
            if c["scheme_id"]:
                self._rows_by_scheme.setdefault(c["scheme_id"], []).append(i)
        self.bm25 = BM25([embedder_mod.document_text(c) for c in self.chunks])
        # One question can need up to three searches (pipeline: unfiltered, scheme-filtered,
        # closest official note); embed it once. Small, thread-safe, bounded.
        self._qvec: dict[str, object] = {}
        self._qvec_lock = threading.Lock()

        mode = (mode or config.SETTINGS.retriever_mode).lower()
        self.embedder, self.store, self.reason = None, None, ""
        if mode == "bm25":
            self.reason = "BOLOSIP_RETRIEVER=bm25"
        elif embedder is not None and store is not None:
            self.embedder, self.store = embedder, store
        else:
            self.embedder, self.store, self.reason = self._open_dense()
            if mode == "embed" and self.store is None:
                raise RuntimeError(f"BOLOSIP_RETRIEVER=embed but embeddings are unavailable: {self.reason}")
        if self.store is None:
            log.info("retriever: BM25 (%s)", self.reason)

    def _open_dense(self):
        emb = embedder_mod.load(allow_download=False)
        if emb is None:
            return None, None, "embedding model unavailable (install the 'embed' extra and run ingest.py --embed-only)"
        vectors, meta = vectorstore.load_vectors()
        if meta is None:
            return None, None, "data/embeddings.npy missing (run ingest.py --embed-only)"
        if meta.get("model") != emb.model_name:
            return None, None, f"vectors were built with {meta.get('model')}, not {emb.model_name}"
        sha = embedder_mod.corpus_hash(self.corpus_path)
        if meta.get("corpus_sha256") != sha:
            return None, None, "vectors are stale: corpus.json changed since they were built"
        store = vectorstore.open_store(self.chunks, sha)
        if store is None:
            return None, None, "ChromaDB unavailable"
        return emb, store, ""

    # -- public ---------------------------------------------------------------

    def backend_name(self) -> str:
        return "dense (nomic + ChromaDB)" if self.store is not None else "bm25"

    def min_score(self, scheme_named: bool = False) -> float:
        if self.store is not None:
            return config.MIN_SCORE_SCHEME if scheme_named else config.MIN_SCORE
        return config.MIN_LEXICAL_SCHEME if scheme_named else config.MIN_LEXICAL

    def candidate_rows(self, scheme_id: str | None) -> list[int]:
        if scheme_id is None:
            return list(range(len(self.chunks)))
        return self._rows_by_scheme.get(scheme_id, []) + self._official_rows

    def search(self, query: str, scheme_id: str | None = None, k: int = 5) -> list[Hit]:
        """Best candidates first. Never returns a fact of a scheme other than `scheme_id`."""
        if scheme_id is not None and scheme_id not in self._rows_by_scheme:
            raise ValueError(f"unknown scheme_id {scheme_id!r}")
        # Boost scheme topics only when a scheme is named: with no scheme, a scheme fact can only
        # lead to "which scheme?", so boosting it would push definitions off the top.
        boosted = phrase_topics(query) if scheme_id is not None else set()
        if self.store is not None:
            try:
                vec = self._embed_query(query)
                n = len(self.candidate_rows(scheme_id))
                hits = [Hit(self.by_id[cid], score, "dense")
                        for cid, score in self.store.query(vec, scheme_id, n) if cid in self.by_id]
                hits = [h for h in hits if scheme_id is None or h.scheme_id in (None, scheme_id)]
                hits.sort(key=lambda h: -(h.score + (config.TOPIC_BOOST if h.topic in boosted else 0.0)))
                return hits[:k]
            except Exception as e:  # model or store failed mid-run: answer with BM25 instead
                log.warning("dense search failed (%s); using BM25 for this query", type(e).__name__)
        scored = self.bm25.score(query, self.candidate_rows(scheme_id))
        bonus = lambda i: config.TOPIC_BOOST_BM25 if self.chunks[i]["topic"] in boosted else 0.0  # noqa: E731
        scored.sort(key=lambda x: (-(x[1] + bonus(x[0])), x[0]))
        return [Hit(self.chunks[i], s, "bm25") for i, s in scored[:k] if s > 0]

    def _embed_query(self, query: str):
        with self._qvec_lock:
            vec = self._qvec.get(query)
        if vec is None:
            vec = self.embedder.embed_query(query)
            with self._qvec_lock:
                if len(self._qvec) >= 512:
                    self._qvec.pop(next(iter(self._qvec)))
                self._qvec[query] = vec
        return vec

    def is_confident(self, hits: list[Hit], scheme_id: str | None = None) -> bool:
        return bool(hits) and hits[0].score >= self.min_score(scheme_id is not None)

    def detect_topic(self, query: str) -> str | None:
        """Topic of the best match across all chunks, if confident (used for follow-ups)."""
        hits = self.search(query)
        return hits[0].topic if self.is_confident(hits) else None


_instance: Retriever | None = None
_lock = threading.Lock()


def get_retriever() -> Retriever:
    """One shared retriever per process (read-only after start-up, architecture §12)."""
    global _instance
    with _lock:
        if _instance is None:
            _instance = Retriever()
        return _instance
