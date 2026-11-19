"""Phase 4 tests: the message-to-reply pipeline (architecture §6, problem statement §4.2).

Offline, with the BM25 retriever so results don't depend on the embedding extra. The
help, plan-variant and conversation sets in eval/datasets run here as subtests;
`dense_only` turns (definition questions, which BM25's high no-scheme bar rejects)
are left to the embed CI job and the Phase 4 gate.
"""
import json
import unittest

from bolosip import config, pipeline
from bolosip.formatter import validate
from bolosip.retriever import Retriever
from eval.answer_eval import check_reply

DATASETS = config.ROOT / "eval" / "datasets"


def load(name):
    return [json.loads(x) for x in (DATASETS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


class PipelineCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = Retriever(mode="bm25")

    def ask(self, text, ctx=None):
        return pipeline.handle(text, ctx, retriever=self.r)


class TestEachKind(PipelineCase):
    """Exit criterion: each of the 7 reply kinds is produced, with the right link."""

    def test_answer(self):
        reply, ctx = self.ask("What is the expense ratio of HDFC Mid Cap Fund?")
        self.assertEqual(reply.kind, "answer")
        self.assertIn("%", reply.text)
        self.assertEqual(reply.source.url, "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth")
        self.assertEqual(ctx["last_scheme"], "hdfc-mid-cap")

    def test_refusal_links_amfi(self):
        reply, _ = self.ask("Should I invest in HDFC Mid Cap Fund?")
        self.assertEqual(reply.kind, "refusal")
        self.assertIn("amfiindia.com", reply.source.url)

    def test_performance_links_factsheet_without_figures(self):
        for q in ("3 year returns of mid cap", "returns?"):                  # PRF-01, PRF-14
            with self.subTest(q=q):
                reply, _ = self.ask(q)
                self.assertEqual(reply.kind, "performance")
                self.assertIn("hdfcfund.com", reply.source.url)
                self.assertNotRegex(reply.text, r"\d")

    def test_privacy_never_echoes_the_value(self):                          # CMP-04
        reply, _ = self.ask("my PAN is ABCDE1234F, what is my folio balance?")
        self.assertEqual(reply.kind, "privacy")
        self.assertNotIn("ABCDE1234F", reply.text)
        self.assertIn("sebi.gov.in", reply.source.url)

    def test_clarify_has_candidates_and_no_link(self):
        reply, _ = self.ask("HDFC Equity expense ratio")                    # SCH-06
        self.assertEqual(reply.kind, "clarify")
        self.assertEqual(set(reply.candidates), {"HDFC Flexi Cap Fund", "HDFC Equity Savings Fund"})
        self.assertIsNone(reply.source)

    def test_clarify_when_several_named(self):                               # SCH-13
        reply, _ = self.ask("exit load of mid cap and small cap")
        self.assertEqual(reply.kind, "clarify")
        self.assertIn("one scheme at a time", reply.text)

    def test_help(self):                                                     # GAP-02
        reply, _ = self.ask("hi")
        self.assertEqual(reply.kind, "help")
        self.assertEqual(reply.candidates, config.EXAMPLE_QUESTIONS)
        self.assertIsNone(reply.footer)

    def test_not_found(self):
        for q in ("expense ratio of SBI Bluechip", "HDFC Bank share price", "HDFC Gold ETF FoF expense ratio",
                  "bitcoin price today"):
            with self.subTest(q=q):
                reply, _ = self.ask(q)
                self.assertEqual(reply.kind, "not_found")
                self.assertEqual(validate(reply), [])


class TestRuleOrder(PipelineCase):
    def test_first_match_wins(self):
        cases = {
            "should I invest? my PAN is ABCDE1234F": "privacy",               # 1 before 2
            "which HDFC fund gave the best returns?": "refusal",              # 2 before 3
            "hi, should I invest in HDFC Mid Cap?": "refusal",                # guards before help
            "what were the 3 year returns of SBI Small Cap": "performance",  # 3 before other-AMC
        }
        for q, kind in cases.items():
            with self.subTest(q=q):
                self.assertEqual(self.ask(q)[0].kind, kind)

    def test_guards_keep_the_thread_scheme(self):                           # CTX-05
        _, ctx = self.ask("HDFC Mid Cap exit load")
        _, ctx2 = self.ask("should I buy it?", ctx)
        self.assertEqual(ctx2, ctx)


class TestSpecialCases(PipelineCase):
    def test_elss_always_says_none_is_elss(self):                            # PS §3.1
        for q in ("What is the ELSS lock-in period?", "Is HDFC Mid Cap an ELSS fund?", "tax saver funds lock in",
                  "HDFC ELSS Tax Saver lock-in"):
            with self.subTest(q=q):
                reply, _ = self.ask(q)
                self.assertRegex(reply.text, r"(?i)none of the 27|not an ELSS")

    def test_scheme_name_only_gives_category(self):                          # SCH-22
        reply, ctx = self.ask("HDFC Mid Cap")
        self.assertIn("classified as", reply.text)
        self.assertEqual(ctx["last_scheme"], "hdfc-mid-cap")

    def test_two_topics_answers_one_and_says_so(self):                       # RET-02
        reply, _ = self.ask("expense ratio and exit load of HDFC Mid Cap Fund")
        self.assertEqual(reply.kind, "answer")
        self.assertIn("You can ask separately about the", reply.text)
        self.assertEqual(validate(reply), [])

    def test_bad_context_is_ignored(self):
        reply, _ = self.ask("what is its exit load?", {"last_scheme": "not-a-scheme"})
        self.assertEqual(reply.kind, "clarify")

    def test_validation_failure_falls_back_to_not_found(self):
        from unittest import mock
        with mock.patch.object(pipeline, "_answer_or_not",
                               return_value=(pipeline.composer.make("answer", "A fact.", url="", as_of="x"), None)):
            reply, _ = self.ask("HDFC Mid Cap exit load")
        self.assertEqual(reply.kind, "not_found")


class TestDatasets(PipelineCase):
    def test_help_set(self):
        cases = load("help")
        self.assertGreaterEqual(len([c for c in cases if c["expect"]["kind"] == "help"]), 15)
        for c in cases:
            with self.subTest(id=c["id"], q=c["question"]):
                self.assertEqual(check_reply(self.r, self.ask(c["question"])[0], c["expect"]), [])

    def test_plan_variants(self):                                            # GAP-05
        for c in load("variants"):
            with self.subTest(id=c["id"], q=c["question"]):
                reply = self.ask(c["question"])[0]
                self.assertEqual(check_reply(self.r, reply, c["expect"]), [])
                if reply.kind == "answer":
                    self.assertTrue(reply.text.startswith("For the Direct Growth plan: "))

    def test_conversations(self):
        convs = load("conversations")
        self.assertGreaterEqual(len(convs), 25)
        for c in convs:
            ctx = {}
            for i, t in enumerate(c["turns"]):
                reply, ctx = self.ask(t["q"], ctx)
                if t["expect"].get("dense_only"):
                    continue
                with self.subTest(id=c["id"], turn=i, q=t["q"]):
                    self.assertEqual(check_reply(self.r, reply, t["expect"]), [])

    def test_core_facts_answer_with_value_and_source(self):                  # AC 1 (extractive)
        for c in load("facts"):
            if c["expect"]["topic"] not in ("expense_ratio", "exit_load", "min_investment", "riskometer", "benchmark"):
                continue
            with self.subTest(id=c["id"]):
                self.assertEqual(check_reply(self.r, self.ask(c["question"])[0], c["expect"]), [])


class TestCli(unittest.TestCase):
    def test_cli_prints_a_cited_answer(self):
        import contextlib
        import io
        import os
        from unittest import mock

        from bolosip import __main__ as cli
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"BOLOSIP_RETRIEVER": "bm25"}), contextlib.redirect_stdout(buf):
            pipeline_retriever = Retriever(mode="bm25")
            with mock.patch.object(pipeline, "get_retriever", return_value=pipeline_retriever):
                self.assertEqual(cli.main(["HDFC Mid Cap exit load", "its benchmark?"]), 0)
        out = buf.getvalue()
        self.assertIn("Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth", out)
        self.assertIn("Last updated from sources:", out)
        self.assertIn("NIFTY Midcap 150", out)


if __name__ == "__main__":
    unittest.main()
