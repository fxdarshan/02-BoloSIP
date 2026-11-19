"""Phase 4 tests: reply formatting and validation (architecture §10, edge cases FMT-01–10)."""
import json
import unittest

from bolosip import composer, config
from bolosip.formatter import Reply, Source, clean_text, make, validate
from bolosip.textutil import split_sentences

CORPUS = json.loads(config.SETTINGS.corpus_path.read_text(encoding="utf-8"))
META = {k: v for k, v in CORPUS.items() if k != "chunks"}


class TestSentences(unittest.TestCase):
    def test_no_split_inside_numbers_or_abbreviations(self):
        for text in ("The TER is 0.73% per annum.", "The AUM is ₹1,00,687.07 crore.",
                     "Minimum SIP is Rs. 100 per month.", "Some schemes, e.g. ELSS, have a lock-in.",
                     "Exit load is approx. 1% within No. of days stated."):
            with self.subTest(text=text):
                self.assertEqual(len(split_sentences(text)), 1)

    def test_three_sentences_kept_four_cut(self):
        three = "One fact. Two facts. Three facts."
        self.assertEqual(clean_text(three), three)                           # FMT-04
        self.assertEqual(clean_text(three + " Four facts."), three)          # FMT-05 (last resort)


class TestCleanText(unittest.TestCase):
    def test_urls_removed_from_body(self):                                  # FMT-06
        text = clean_text("See https://www.amfiindia.com/investor for details. Exit load is 1%.")
        self.assertNotIn("http", text)
        self.assertIn("Exit load is 1%.", text)

    def test_empty_brackets_left_by_url_removed(self):
        self.assertEqual(clean_text("Details are on the page (https://x.example/a)."), "Details are on the page.")


class TestValidate(unittest.TestCase):
    def ok(self, **kw):
        base = dict(kind="answer", text="The TER is 0.73% per annum.",
                    source=Source("https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth", "Groww"),
                    footer="Last updated from sources: 16 Nov 2026")
        base.update(kw)
        return Reply(**base)

    def test_valid_answer(self):
        self.assertEqual(validate(self.ok()), [])

    def test_footer_exact_format(self):                                      # FMT-07
        self.assertEqual(make("answer", "A fact.", url="https://a.example", as_of="16 Nov 2026").footer,
                         "Last updated from sources: 16 Nov 2026")
        self.assertTrue(validate(self.ok(footer="Last updated: 16 Nov 2026")))
        self.assertTrue(validate(self.ok(footer="Last updated from sources: 2026-11-16")))
        self.assertTrue(validate(self.ok(footer=None)))                       # FMT-09

    def test_one_link_only(self):
        self.assertTrue(validate(self.ok(text="See https://a.example for the TER.")))
        self.assertTrue(validate(self.ok(source=None)))
        self.assertTrue(validate(self.ok(source=Source("http://insecure.example", "x"))))

    def test_sentence_limits(self):
        self.assertTrue(validate(self.ok(text="One. Two. Three. Four.")))
        self.assertTrue(validate(self.ok(text=" ")))

    def test_clarify_and_help_have_no_link_or_footer(self):                  # FMT-10
        c = composer.clarify(["hdfc-flexi-cap", "hdfc-equity-savings"])
        self.assertEqual(validate(c), [])
        self.assertIsNone(c.source)
        self.assertIsNone(c.footer)
        self.assertTrue(validate(Reply("clarify", "Which one?", Source("https://a.example", "x"))))
        self.assertTrue(validate(Reply("clarify", "Which one?", candidates=tuple("abcdef"))))
        self.assertEqual(validate(composer.help_reply()), [])

    def test_to_dict_is_json(self):
        d = composer.refusal(META).to_dict()
        self.assertEqual(set(d), {"kind", "text", "source", "footer", "scheme_id", "candidates"})
        json.dumps(d)


class TestEveryChunk(unittest.TestCase):
    def test_every_chunk_is_a_valid_answer_unchanged(self):
        """Exit criterion: validate() passes for every chunk, and extractive text is never cut."""
        for c in CORPUS["chunks"]:
            with self.subTest(id=c["id"]):
                reply = composer.answer("q", c)
                self.assertEqual(validate(reply), [])
                self.assertEqual(reply.text, " ".join(c["text"].split()))
                self.assertEqual(reply.source.url, c["source_url"])
                self.assertEqual(reply.footer, f"Last updated from sources: {c['as_of']}")


class TestFixedReplies(unittest.TestCase):
    def test_every_fixed_reply_is_valid(self):
        replies = [composer.refusal(META), composer.performance(META), composer.performance(META, "hdfc-mid-cap"),
                   composer.privacy(META), composer.not_found(META), composer.other_amc(META),
                   composer.non_fund(META), composer.not_covered(META, "hdfc gold etf fund"),
                   composer.direct_growth_only(META, "hdfc-mid-cap", "expense_ratio", "Regular plan's"),
                   composer.ask_for_scheme(), composer.help_reply(),
                   composer.clarify([s for s in META["schemes"]][:9])]
        for reply in replies:
            with self.subTest(kind=reply.kind, text=reply.text[:40]):
                self.assertEqual(validate(reply), [])

    def test_links_per_kind(self):                                           # arch §10.1
        self.assertIn("amfiindia.com", composer.refusal(META).source.url)
        self.assertIn("sebi.gov.in", composer.privacy(META).source.url)
        self.assertIn("hdfcfund.com", composer.performance(META).source.url)

    def test_no_figures_in_performance(self):
        for sid in (None, "hdfc-mid-cap"):
            self.assertNotRegex(composer.performance(META, sid).text, r"\d")

    def test_clarify_lists_at_most_five(self):                               # SCH-21
        c = composer.clarify(list(META["schemes"])[:9])
        self.assertEqual(len(c.candidates), 5)
        self.assertIn("4 more", c.text)

    def test_names_display(self):
        self.assertEqual(composer.display_name("hdfc gold etf fund of fund"), "HDFC Gold ETF Fund Of Fund")


if __name__ == "__main__":
    unittest.main()
