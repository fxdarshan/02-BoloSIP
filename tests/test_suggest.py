"""Question suggestions (bolosip/suggest.py, web/index.html).

Every question the UI can suggest (typing suggestions, "Ask next" and "Try instead"
chips) must get a correct, cited answer: a suggestion that leads to "not found" would
be worse than none (chatbot-flow-design: suggest the bot's actual capabilities).
"""
import json
import unittest

from bolosip import config, pipeline, registry, suggest
from bolosip.formatter import validate
from bolosip.retriever import Retriever
from eval.answer_eval import answered_chunk


class TestIndex(unittest.TestCase):
    def test_shape_and_size(self):
        ix = suggest.suggestion_index()
        self.assertEqual(len(ix["schemes"]), 27)
        self.assertEqual([t["id"] for t in ix["topics"]][:5],
                         ["expense_ratio", "exit_load", "min_investment", "riskometer", "benchmark"])
        self.assertEqual({s["id"] for s in ix["schemes"]}, {s.id for s in registry.SCHEMES})
        for s in ix["schemes"]:
            self.assertTrue(s["keys"] and s["name"].lower().split()[1] in s["keys"].split())
        for t in ix["topics"]:
            self.assertIn("{name}", t["template"])
            self.assertTrue(t["keys"])
        self.assertLess(len(json.dumps(ix)), 10_000)            # sent with every page load
        for q in config.EXAMPLE_QUESTIONS:
            self.assertIn(q, ix["general"])


class TestEverySuggestionAnswers(unittest.TestCase):
    """BM25 fallback (no extras): every scheme suggestion, and the general questions the
    server offers for this retriever. The dense path is checked by the embed CI job."""

    @classmethod
    def setUpClass(cls):
        cls.r = Retriever()

    def test_scheme_suggestions_give_that_schemes_fact(self):
        for q, sid, topic in suggest.all_questions():
            if sid is None:
                continue
            with self.subTest(q=q):
                reply, _ = pipeline.handle(q, {}, retriever=self.r)
                self.assertEqual(reply.kind, "answer")
                self.assertEqual(validate(reply), [])
                chunk = answered_chunk(self.r, reply)
                self.assertEqual((chunk["scheme_id"], chunk["topic"]), (sid, topic))

    def test_offered_general_questions_answer(self):
        offered = suggest.suggestion_index(self.r)["general"]
        self.assertGreaterEqual(len(offered), 3)
        for q in offered:
            with self.subTest(q=q):
                self.assertEqual(pipeline.handle(q, {}, retriever=self.r)[0].kind, "answer")
        if self.r.store is not None:                            # dense: all of them work
            self.assertEqual(offered, list(suggest.GENERAL_QUESTIONS))

    def test_chip_questions_never_depend_on_thread_context(self):
        """Chips send full questions, so they work even in a thread about another scheme."""
        ctx = {"last_scheme": "hdfc-liquid"}
        reply, _ = pipeline.handle("What is the exit load of HDFC Mid Cap Fund?", ctx, retriever=self.r)
        self.assertEqual(reply.scheme_id, "hdfc-mid-cap")


if __name__ == "__main__":
    unittest.main()
