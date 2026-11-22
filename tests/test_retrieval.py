"""Phase 3 tests: retrieval (architecture §8) and the full Phase 3 decision.

Default tests run offline with no third-party packages: the BM25 backend, plus the
dense code path through a pure-Python stand-in embedder and store. Tests marked
"real model" run only where the `embed` extra is installed and the model is cached
(the Python 3.12 CI job and a local .venv).
"""
import json
import math
import re
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from bolosip import config, embedder, registry, vectorstore
from bolosip.retriever import Retriever, phrase_topics
from bolosip.topics import OFFICIAL_TOPICS, SCHEME_TOPICS
from eval.retrieval_eval import decide, is_correct, load

CORPUS = json.loads(config.SETTINGS.corpus_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Pure-Python stand-ins for the dense path (no numpy, no model)
# ---------------------------------------------------------------------------

def _bag(text: str) -> dict[str, float]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    vec = {w: words.count(w) for w in set(words)}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {w: v / norm for w, v in vec.items()}


class StubEmbedder:
    model_name = "stub"

    def embed_query(self, text):
        return _bag(text)


class StubStore:
    """Mimics VectorStore.query: cosine over bag-of-words, with the scheme filter."""

    def __init__(self, chunks):
        self.rows = [(c["id"], c["scheme_id"], _bag(embedder.document_text(c))) for c in chunks]
        self.calls = []

    def query(self, vec, scheme_id=None, n=5):
        self.calls.append(scheme_id)
        out = []
        for cid, sid, doc in self.rows:
            if scheme_id and sid not in (None, scheme_id):
                continue
            out.append((cid, sum(vec.get(w, 0.0) * x for w, x in doc.items())))
        return sorted(out, key=lambda x: -x[1])[:n]


def _short(s: registry.Scheme) -> str:
    return s.name.replace("HDFC ", "").replace(" Fund", "")


class TestBM25(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = Retriever(mode="bm25")

    def test_backend(self):
        self.assertEqual(self.r.backend_name(), "bm25")
        self.assertIn("BOLOSIP_RETRIEVER=bm25", self.r.reason)

    def test_expense_ratio_for_all_27_schemes(self):  # exit criterion
        for s in registry.SCHEMES:
            with self.subTest(scheme=s.id):
                hits = self.r.search(f"HDFC {_short(s)} expense ratio", s.id)
                self.assertEqual(hits[0].chunk["id"], f"{s.id}:expense_ratio")

    def test_topic_detection_for_every_scheme_topic(self):
        questions = {
            "expense_ratio": "expense ratio", "exit_load": "exit load", "min_investment": "minimum SIP amount",
            "riskometer": "riskometer level", "benchmark": "benchmark index", "lock_in": "lock-in period",
            "fund_manager": "who is the fund manager", "category": "investment objective", "nav": "NAV",
            "aum": "fund size AUM", "scheme_details": "ISIN and launch date", "stamp_duty": "stamp duty",
        }
        self.assertEqual(set(questions), set(SCHEME_TOPICS))
        for topic, words in questions.items():
            with self.subTest(topic=topic):
                self.assertEqual(self.r.search(f"{words} of HDFC Mid Cap Fund", "hdfc-mid-cap")[0].topic, topic)

    def test_topic_detection_for_every_official_topic(self):
        questions = {
            "statement": "how do I download my account statement", "capital_gains": "capital gains statement",
            "lock_in_general": "ELSS lock-in period", "riskometer_general": "riskometer six levels",
            "expense_ratio_general": "what is total expense ratio TER meaning",
            "exit_load_general": "what is exit load meaning", "plans_general": "difference between direct and regular plan",
            "sip_general": "what is a systematic investment plan SIP", "factsheet": "HDFC monthly factsheet",
        }
        self.assertEqual(set(questions), set(OFFICIAL_TOPICS))
        for topic, q in questions.items():
            with self.subTest(topic=topic):
                # Ranking, not confidence: BM25's no-scheme answer bar is deliberately high.
                self.assertEqual(self.r.search(q)[0].topic, topic)

    def test_scheme_filter_never_returns_another_scheme(self):
        for s in registry.SCHEMES:
            for h in self.r.search("expense ratio exit load benchmark NAV HDFC Small Cap Fund", s.id, k=40):
                self.assertIn(h.scheme_id, (None, s.id))

    def test_unknown_scheme_rejected(self):
        with self.assertRaises(ValueError):
            self.r.search("exit load", "hdfc-not-a-scheme")

    def test_topic_phrases_rank_neighbours(self):
        self.assertEqual(phrase_topics("management fee of HDFC Small Cap"), {"expense_ratio"})
        self.assertEqual(phrase_topics("assets under management for HDFC Equity Savings"), {"aum"})
        self.assertIn("lock_in", phrase_topics("how long is my money stuck"))

    def test_search_is_fast(self):
        start = time.perf_counter()
        for _ in range(20):
            self.r.search("what is the exit load of HDFC Mid Cap Fund", "hdfc-mid-cap")
            self.r.search("how do I download my statement")
        self.assertLess((time.perf_counter() - start) / 40, 0.005)


class TestDensePathWithStubs(unittest.TestCase):
    """The dense code path, offline: filter, ordering and failure fallback."""

    def setUp(self):
        self.store = StubStore(CORPUS["chunks"])
        self.r = Retriever(embedder=StubEmbedder(), store=self.store)

    def test_backend_and_filter(self):
        self.assertTrue(self.r.backend_name().startswith("dense"))
        hits = self.r.search("exit load", "hdfc-liquid", k=30)
        self.assertEqual(self.store.calls[-1], "hdfc-liquid")
        self.assertTrue(all(h.scheme_id in (None, "hdfc-liquid") for h in hits))
        self.assertIn("hdfc-liquid:exit_load", [h.chunk["id"] for h in hits[:3]])

    def test_store_failure_falls_back_to_bm25_for_that_query(self):
        class Broken(StubStore):
            def query(self, *a, **k):
                raise RuntimeError("store down")
        r = Retriever(embedder=StubEmbedder(), store=Broken(CORPUS["chunks"]))
        hits = r.search("exit load of HDFC Liquid Fund", "hdfc-liquid")
        self.assertEqual(hits[0].backend, "bm25")


class TestBackendSelection(unittest.TestCase):
    def test_embed_mode_requires_embeddings(self):
        embedder.reset_cache()
        try:
            import fastembed  # noqa: F401
            has_extra = True
        except ImportError:
            has_extra = False
        if has_extra and _model_cached():
            self.skipTest("embeddings are available here")
        with self.assertRaises(RuntimeError):
            Retriever(mode="embed")

    def test_auto_falls_back_with_a_reason(self):
        r = Retriever(mode="auto")
        if r.store is None:
            self.assertEqual(r.backend_name(), "bm25")
            self.assertTrue(r.reason)

    def test_stale_vectors_are_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed = Path(tmp) / "corpus.json"
            data = json.loads(config.SETTINGS.corpus_path.read_text(encoding="utf-8"))
            data["built_on"] = "01 Jan 2000"          # any change alters the corpus hash
            changed.write_text(json.dumps(data), encoding="utf-8")
            r = Retriever(corpus_path=changed, mode="auto")
            self.assertEqual(r.backend_name(), "bm25")
            if _dense_available():
                self.assertIn("stale", r.reason)

    def test_damaged_vector_metadata_is_detected(self):
        """ISS-024: a mangled chunk id in embeddings.json passed the hash check and crashed
        the Chroma rebuild. It is now reported, and the dense path is never opened with it."""
        chunks = CORPUS["chunks"]
        ids = [c["id"] for c in chunks]
        rows = [0] * len(ids)                               # only the row count matters here
        self.assertIsNone(vectorstore.mismatch(rows, {"chunk_ids": ids}, chunks))
        damaged = list(ids)
        damaged[ids.index("hdfc-balanced-advantage:category")] = "hdfcalanced-advantage:category"
        problem = vectorstore.mismatch(rows, {"chunk_ids": damaged}, chunks)
        self.assertIn("hdfcalanced-advantage:category", problem)
        self.assertIn("rows", vectorstore.mismatch(rows[:-1], {"chunk_ids": ids}, chunks))
        self.assertIn("order", vectorstore.mismatch(rows, {"chunk_ids": ids[::-1]}, chunks))
        self.assertIn("missing", vectorstore.mismatch(None, None, chunks))


class TestDecision(unittest.TestCase):
    """Guards -> resolver -> filtered search -> threshold (BM25, offline)."""

    @classmethod
    def setUpClass(cls):
        cls.r = Retriever(mode="bm25")

    def test_other_amc_and_non_fund(self):  # GAP-01, SCH-16, SCH-17
        for q in ("expense ratio of SBI Bluechip", "SBI Small Cap exit load", "Axis Midcap TER",
                  "Nippon India Multi Cap", "HDFC Bank fixed deposit interest rate"):
            with self.subTest(q=q):
                self.assertEqual(decide(self.r, q).kind, "not_found")

    def test_not_covered_hdfc_scheme(self):  # SCH-18
        self.assertEqual(decide(self.r, "HDFC Gold ETF Fund of Fund expense ratio").kind, "not_found")

    def test_confusable_names_clarify(self):  # AC 7a
        for q in ("HDFC Equity expense ratio", "large cap index fund exit load", "multi fund NAV",
                  "exit load of mid cap and small cap"):
            with self.subTest(q=q):
                self.assertEqual(decide(self.r, q).kind, "clarify")

    def test_follow_up_uses_thread_scheme(self):  # CTX-01
        d = decide(self.r, "what about its exit load", last_scheme="hdfc-mid-cap")
        self.assertEqual((d.kind, d.chunk_id), ("answer", "hdfc-mid-cap:exit_load"))

    def test_scheme_fact_without_scheme_is_never_answered(self):  # rule 4
        # BM25's high no-scheme bar gives not_found; the dense model asks which scheme (real-model test).
        self.assertIn(decide(self.r, "what is the exit load of the fund?").kind, ("clarify", "not_found"))

    def test_guards_run_first(self):
        self.assertEqual(decide(self.r, "should I invest in HDFC Mid Cap?").kind, "refusal")
        self.assertEqual(decide(self.r, "3 year returns of HDFC Mid Cap").kind, "performance")

    def test_ambiguous_set(self):
        for c in load("ambiguous"):
            with self.subTest(id=c["id"]):
                self.assertTrue(is_correct(self.r, c, decide(self.r, c["question"])))

    def test_no_out_of_scope_question_is_answered(self):
        for c in load("out_of_corpus") + [c for c in load("holdout") if c["expect"]["kind"] != "answer"]:
            with self.subTest(id=c["id"]):
                self.assertNotEqual(decide(self.r, c["question"]).kind, "answer")


# ---------------------------------------------------------------------------
# Real model (Python 3.10–3.14 with the `embed` extra and the model cached)
# ---------------------------------------------------------------------------

def _model_cached() -> bool:
    return any(config.SETTINGS.model_cache.glob("models--nomic-ai--nomic-embed-text-v1.5*"))


def _dense_available() -> bool:
    try:
        import chromadb  # noqa: F401
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return _model_cached() and config.EMBEDDINGS_NPY.exists()


# With BOLOSIP_RETRIEVER=embed (the CI embed job) these must run, never silently skip.
@unittest.skipUnless(_dense_available() or os.environ.get("BOLOSIP_RETRIEVER") == "embed",
                     "needs the 'embed' extra and the cached model")
class TestRealModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = Retriever(mode="embed")

    def _accuracy(self, cases):
        ok = sum(is_correct(self.r, c, decide(self.r, c["question"])) for c in cases)
        return ok / len(cases)

    def test_backend(self):
        self.assertEqual(self.r.backend_name(), "dense (nomic + ChromaDB)")

    def test_expense_ratio_for_all_27_schemes(self):
        for s in registry.SCHEMES:
            with self.subTest(scheme=s.id):
                self.assertEqual(self.r.search(f"HDFC {_short(s)} expense ratio", s.id)[0].chunk["id"],
                                 f"{s.id}:expense_ratio")

    def test_paraphrases_at_least_90_percent(self):
        self.assertGreaterEqual(self._accuracy(load("paraphrases")), 0.90)

    def test_holdout_at_least_90_percent(self):
        self.assertGreaterEqual(self._accuracy([c for c in load("holdout") if c["expect"]["kind"] == "answer"]), 0.90)

    def test_no_out_of_scope_question_is_answered(self):
        for c in load("out_of_corpus") + [c for c in load("holdout") if c["expect"]["kind"] != "answer"]:
            with self.subTest(id=c["id"]):
                self.assertNotEqual(decide(self.r, c["question"]).kind, "answer")

    def test_chroma_matches_exact_search(self):
        """Chroma's approximate index returns the same top hit as exact cosine over the .npy copy."""
        import numpy as np
        vectors, meta = vectorstore.load_vectors()
        ids = meta["chunk_ids"]
        for c in load("paraphrases")[:40]:
            q = self.r.embedder.embed_query(c["question"])
            exact = ids[int(np.argmax(vectors @ q))]
            with self.subTest(q=c["question"]):
                self.assertEqual(self.r.store.query(q, None, 1)[0][0], exact)

    def test_scheme_fact_without_scheme_asks_which(self):  # rule 4
        self.assertEqual(decide(self.r, "what is the exit load of the fund?").kind, "clarify")

    def test_collection_is_rebuilt_when_missing(self):
        # ignore_cleanup_errors: on Windows Chroma keeps its index file open for the process.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            vectorstore.reset_cache()
            sha = embedder.corpus_hash(config.SETTINGS.corpus_path)
            start = time.perf_counter()
            store = vectorstore.open_store(CORPUS["chunks"], sha, Path(tmp) / "chroma")
            self.assertLess(time.perf_counter() - start, 2.0)     # exit criterion: < 2 s
            self.assertEqual(store.count, len(CORPUS["chunks"]))
            del store
            vectorstore.reset_cache()
            from chromadb.api.client import SharedSystemClient
            SharedSystemClient.clear_system_cache()
            shutil.rmtree(Path(tmp) / "chroma", ignore_errors=True)

    def test_speed(self):
        q = self.r.embedder.embed_query("what is the exit load of HDFC Mid Cap Fund")
        start = time.perf_counter()
        for _ in range(10):
            self.r.store.query(q, "hdfc-mid-cap", 22)
        self.assertLess((time.perf_counter() - start) / 10, 0.010)    # search < 10 ms
        start = time.perf_counter()
        for _ in range(5):
            self.r.embedder.embed_query("how much does HDFC Mid Cap charge every year")
        self.assertLess((time.perf_counter() - start) / 5, 0.100)    # query embedding < 100 ms


if __name__ == "__main__":
    unittest.main()
