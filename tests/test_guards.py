"""Phase 2 tests: personal-data, advice and returns guards (architecture §11).

Every case in eval/datasets/{advice,performance,pii}.jsonl runs here as a
subtest, so the evaluation sets and the unit tests can never disagree. Extra
unit tests cover redaction, public identifiers, rule order, the corpus and
regex speed.
"""
import json
import time
import unittest
from pathlib import Path

from bolosip import guards
from bolosip.config import ROOT

DATASETS = ROOT / "eval" / "datasets"


def load(name: str) -> list[dict]:
    return [json.loads(line) for line in (DATASETS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


class TestDatasets(unittest.TestCase):
    def _run(self, name: str, minimum_positive: int):
        cases = load(name)
        positives = [c for c in cases if c["expect"]["kind"] is not None]
        self.assertGreaterEqual(len(positives), minimum_positive, f"{name}: too few positive cases")
        for c in cases:
            with self.subTest(id=c["id"], question=c["question"]):
                self.assertEqual(guards.check(c["question"]).kind, c["expect"]["kind"])

    def test_advice_set(self):
        self._run("advice", 60)

    def test_performance_set(self):
        self._run("performance", 30)

    def test_pii_set(self):
        self._run("pii", 30)

    def test_pii_values_never_survive_redaction(self):
        for c in load("pii"):
            for value in c["expect"].get("values", []):
                with self.subTest(id=c["id"], value=value):
                    self.assertNotIn(value.lower(), guards.redact(c["question"]).lower())

    def test_ids_are_unique(self):
        ids = [c["id"] for name in ("advice", "performance", "pii") for c in load(name)]
        self.assertEqual(len(ids), len(set(ids)))


class TestRuleOrder(unittest.TestCase):
    def test_privacy_before_advice_and_returns(self):
        self.assertEqual(guards.check("My mobile is 9123456789, should I invest?").kind, "privacy")
        self.assertEqual(guards.check("OTP 551199 - what were the 3 year returns?").kind, "privacy")

    def test_advice_before_returns(self):  # ADV-24
        self.assertEqual(guards.check("Which fund gave better returns?").kind, "refusal")
        self.assertTrue(guards.is_performance("Which fund gave better returns?"))

    def test_plain_fact_passes_through(self):
        r = guards.check("What is the exit load of HDFC Mid Cap Fund?")
        self.assertIsNone(r.kind)
        self.assertEqual(r.pii, ())

    def test_privacy_reports_kinds_not_values(self):
        r = guards.check("PAN ABCDE1234F and mail me@example.com")
        self.assertEqual(r.kind, "privacy")
        self.assertEqual(set(r.pii), {"PAN", "email address"})
        self.assertNotIn("ABCDE1234F", repr(r))


class TestRedaction(unittest.TestCase):
    def test_keeps_sentence_readable(self):
        self.assertEqual(guards.redact("my PAN is ABCDE1234F, what is the exit load?"),
                         "my PAN is [redacted], what is the exit load?")
        self.assertEqual(guards.redact("my aadhaar is 2345 6789 0123"), "my aadhaar is [redacted]")
        self.assertEqual(guards.redact("aadhaar ending 4567"), "aadhaar ending [redacted]")

    def test_multiple_values(self):
        out = guards.redact("PAN ABCDE1234F, phone 9876543210 and mail a.b@example.org")
        self.assertEqual(out.count("[redacted]"), 3)
        for v in ("ABCDE1234F", "9876543210", "a.b@example.org"):
            self.assertNotIn(v, out)

    def test_text_without_pii_unchanged(self):
        for text in ("What is the NAV of HDFC Liquid Fund?", "expense ratio of 0.73% per annum",
                     "AUM of ₹1,00,687 crore"):
            with self.subTest(text=text):
                self.assertEqual(guards.redact(text), text)

    def test_public_identifiers_kept(self):  # Phase 2 task 5
        for text in ("ISIN INF179K01XQ0", "scheme code 118989", "RTA code HMCOGT",
                     "HDFC toll free 1800-3010-6767"):
            with self.subTest(text=text):
                self.assertEqual(guards.find_pii(text), [])
                self.assertEqual(guards.redact(text), text)

    def test_isin_next_to_real_pii(self):
        out = guards.redact("ISIN INF179K01XQ0 and my PAN ABCDE1234F")
        self.assertIn("INF179K01XQ0", out)
        self.assertNotIn("ABCDE1234F", out)


class TestCorpusAndFacts(unittest.TestCase):
    """Stored facts must never trip a guard: Phase 7 runs is_advisory() on LLM output."""

    def test_corpus_chunks_are_clean(self):
        corpus = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
        for c in corpus["chunks"]:
            with self.subTest(id=c["id"]):
                self.assertEqual(guards.find_pii(c["text"]), [])
                self.assertFalse(guards.is_advisory(c["text"]))

    def test_fact_questions_pass_through(self):
        for c in load("facts") + load("general"):
            with self.subTest(id=c["id"]):
                self.assertIsNone(guards.check(c["question"]).kind)


class TestDocumentedLimits(unittest.TestCase):
    def test_pii_29_split_across_messages_not_joined(self):
        # Documented limit (edge-case PII-29): each message is checked on its own.
        self.assertIsNone(guards.check("my PAN starts ABCDE").kind)
        self.assertIsNone(guards.check("and ends 1234F").kind)
        self.assertEqual(guards.check("my PAN starts ABCDE and ends 1234F").kind, None)
        self.assertEqual(guards.check("ABCDE1234F").kind, "privacy")


class TestSpeed(unittest.TestCase):
    """No catastrophic backtracking: every guard stays fast on a 500-character input."""

    WORST_CASES = [
        "a" * 500, "1" * 500, "1 " * 250, "@" * 500, "a@" * 250, "a." * 250, "at " * 166,
        "x" * 499 + "@", "should " * 71, "which fund " * 45, "will the " * 55, "is the " * 71,
        "expense ratio " * 35, "aadhaar " * 62, "returns " * 62, "how did the " * 41,
        ("ABCDE1234F " * 46)[:500], ("2345 6789 0123 " * 34)[:500], "INF179K01XQ0" * 41,
    ]

    PATTERNS = {**guards.PII_PATTERNS, "public id": guards._PUBLIC_ID, "advisory": guards._ADVISORY,
                "performance": guards._PERFORMANCE, "not performance": guards._NOT_PERFORMANCE}

    def test_each_regex_under_5ms(self):  # Phase 2 exit criterion
        for name, pattern in self.PATTERNS.items():
            for text in self.WORST_CASES:
                with self.subTest(pattern=name, text=text[:20]):
                    self.assertLessEqual(len(text), 500)
                    best = min(self._time(lambda: pattern.search(text)) for _ in range(5))
                    self.assertLess(best, 0.005, f"{best * 1000:.2f} ms")

    def test_full_check_and_redact_stay_fast(self):
        for text in self.WORST_CASES:
            with self.subTest(text=text[:20]):
                best = min(self._time(lambda: (guards.check(text), guards.redact(text))) for _ in range(5))
                self.assertLess(best, 0.025, f"{best * 1000:.2f} ms")

    @staticmethod
    def _time(fn) -> float:
        start = time.perf_counter()
        fn()
        return time.perf_counter() - start


if __name__ == "__main__":
    unittest.main()
