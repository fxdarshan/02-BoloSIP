"""Phase 1 tests: registry, parsing, chunk templates, validation, atomic write, lock.

All offline. Exact values come from small frozen fixtures in tests/fixtures/
(trimmed copies of three scheme pages saved on 16 Nov 2026), so these tests
don't change when data/raw is refreshed.
"""
import copy
import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import ingest
from bolosip import registry
from bolosip.config import HDFC_FACTSHEET_URL, ROOT
from bolosip.textutil import RETURN_FIGURE, split_sentences
from bolosip.topics import CORE_TOPICS, SCHEME_TOPICS, SEBI_RISK_LEVELS

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = "16 Nov 2026"


def page(scheme_id: str) -> dict:
    return ingest.parse_page((FIXTURES / f"{scheme_id}.html").read_text(encoding="utf-8"))


def chunks_for(scheme_id: str, d: dict | None = None) -> dict:
    s = registry.BY_ID[scheme_id]
    out = ingest.scheme_chunks(s, d if d is not None else page(scheme_id), AS_OF, AS_OF)
    return {c["topic"]: c for c in out}


class TestRegistry(unittest.TestCase):
    def test_registry_is_sound(self):
        self.assertEqual(registry.check_registry(), [])

    def test_urls_match_problem_statement_exactly(self):
        text = (ROOT / "Doc" / "problem_statement.md").read_text(encoding="utf-8")
        section = text.split("### 3.1", 1)[1].split("### 3.2", 1)[0]
        doc_urls = set(re.findall(r"https://groww\.in/mutual-funds/[a-z0-9-]+", section))
        self.assertEqual(len(doc_urls), 27)
        self.assertEqual(set(registry.ALLOWED_URLS), doc_urls)

    def test_extra_or_missing_scheme_is_reported(self):
        fewer = registry.SCHEMES[:-1]
        extra = registry.SCHEMES + (registry.SCHEMES[0],)
        for schemes in (fewer, extra):
            with self.subTest(n=len(schemes)), mock.patch.object(registry, "SCHEMES", schemes):
                self.assertTrue(registry.check_registry())

    def test_flexi_cap_uses_former_name_url(self):
        s = registry.BY_ID["hdfc-flexi-cap"]
        self.assertTrue(s.url.endswith("hdfc-equity-fund-direct-growth"))
        self.assertIn("hdfc equity fund", s.aliases)

    def test_shared_ambiguous_aliases(self):
        index = registry.alias_index()
        self.assertEqual(set(index["hdfc equity"]), {"hdfc-flexi-cap", "hdfc-equity-savings"})
        self.assertEqual(set(index["large cap index"]), {"hdfc-nifty-50-index", "hdfc-bse-sensex-index"})
        self.assertEqual(set(index["multi"]), {"hdfc-multi-cap", "hdfc-multi-asset-allocation"})
        self.assertEqual(index["large cap"], ("hdfc-large-cap",))


class TestFetchAllowList(unittest.TestCase):
    def test_refuses_urls_outside_registry(self):
        for url in ("https://groww.in/mutual-funds/sbi-small-cap-fund-direct-growth",
                    "https://example.com/", "https://groww.in/mutual-funds/amc/hdfc-mutual-funds"):
            with self.subTest(url=url):
                with self.assertRaises(ingest.IngestError):
                    ingest.fetch(url)


class TestParsing(unittest.TestCase):
    def test_missing_embedded_data(self):
        with self.assertRaises(ingest.IngestError):
            ingest.parse_page("<html><body>no data</body></html>")

    def test_identity_check(self):
        d = page("hdfc-mid-cap")
        ingest.check_identity(registry.BY_ID["hdfc-mid-cap"], d)
        with self.assertRaises(ingest.IngestError):
            ingest.check_identity(registry.BY_ID["hdfc-small-cap"], d)       # redirect to wrong scheme
        bad = dict(d, isin="INF000X00000")
        with self.assertRaises(ingest.IngestError):
            ingest.check_identity(registry.BY_ID["hdfc-mid-cap"], bad)
        closed = dict(d, closed_scheme=True)
        with self.assertRaises(ingest.IngestError):
            ingest.check_identity(registry.BY_ID["hdfc-mid-cap"], closed)


class TestRiskometer(unittest.TestCase):
    def test_reads_scheme_own_value_not_stale_nfo_value(self):
        d = page("hdfc-mid-cap")
        self.assertEqual(d["nfo_risk"], "Moderately High")      # stale launch-time value on the page
        self.assertEqual(ingest.riskometer(d), "Very High")      # the scheme's current level
        self.assertEqual(ingest.riskometer(page("hdfc-liquid")), "Moderate")

    def test_peer_value_first_in_page_is_ignored(self):  # GAP-03
        d = page("hdfc-liquid")
        d = dict(d, peerComparison=[{"risk": "Very High"}] + d.get("peerComparison", []))
        d["return_stats"] = [{"scheme_code": "999999", "risk": "Very High"}] + d["return_stats"]
        self.assertEqual(ingest.riskometer(d), "Moderate")

    def test_mismatch_with_summary_fails(self):
        d = page("hdfc-mid-cap")
        d = dict(d, meta_desc=d["meta_desc"].replace("Very High", "Low"))
        with self.assertRaises(ingest.IngestError):
            ingest.riskometer(d)

    def test_level_outside_sebi_levels_fails(self):
        d = page("hdfc-mid-cap")
        d["return_stats"] = [dict(d["return_stats"][0], risk="Medium")]
        d["meta_desc"] = ""
        with self.assertRaises(ingest.IngestError):
            ingest.riskometer(d)


class TestChunkTemplates(unittest.TestCase):
    def test_twelve_topics_each_one_to_three_sentences(self):
        for sid in ("hdfc-mid-cap", "hdfc-liquid", "hdfc-silver-etf-fof"):
            chunks = chunks_for(sid)
            with self.subTest(scheme=sid):
                self.assertEqual(set(chunks), set(SCHEME_TOPICS))
                for c in chunks.values():
                    self.assertTrue(1 <= len(split_sentences(c["text"])) <= 3, c["text"])

    def test_equity_values(self):
        c = chunks_for("hdfc-mid-cap")
        self.assertIn("0.73% per annum, as on 12 Nov 2026", c["expense_ratio"]["text"])
        self.assertEqual(c["exit_load"]["text"],
                         "HDFC Mid Cap Fund (Direct Growth) has an exit load of 1% if redeemed within 1 year.")
        self.assertIn("minimum SIP amount for HDFC Mid Cap Fund (Direct Growth) is ₹100", c["min_investment"]["text"])
        self.assertIn('"Very High"', c["riskometer"]["text"])
        self.assertIn("NIFTY Midcap 150 Total Return Index", c["benchmark"]["text"])
        self.assertIn("Chirag Setalvad", c["fund_manager"]["text"])
        self.assertIn("₹229.697 as on 13 Nov 2026", c["nav"]["text"])
        self.assertIn("₹1,00,687.07 crore", c["aum"]["text"])
        self.assertIn("INF179K01XQ0", c["scheme_details"]["text"])
        self.assertIn("no lock-in period", c["lock_in"]["text"])

    def test_debt_values(self):
        c = chunks_for("hdfc-liquid")
        self.assertIn("0.20% per annum", c["expense_ratio"]["text"])
        self.assertIn("0.0070% if redeemed within 1 day", c["exit_load"]["text"])
        self.assertIn("0.0045% if redeemed within 6 days", c["exit_load"]["text"])
        self.assertIn('"Moderate"', c["riskometer"]["text"])
        self.assertIn("CRISIL Liquid Debt A-I Index", c["benchmark"]["text"])
        self.assertIn("as on 15 Nov 2026", c["nav"]["text"])

    def test_fof_values(self):
        c = chunks_for("hdfc-silver-etf-fof")
        self.assertIn("0.22% per annum", c["expense_ratio"]["text"])
        self.assertIn("1%, if redeemed within 15 days", c["exit_load"]["text"])
        self.assertIn("Domestic Price of Silver", c["benchmark"]["text"])
        self.assertIn("FoF – Silver in the Fund of Funds group", c["category"]["text"])

    def test_every_fact_cites_its_own_scheme_page(self):
        for sid in ("hdfc-mid-cap", "hdfc-liquid"):
            for c in chunks_for(sid).values():
                self.assertEqual(c["source_url"], registry.BY_ID[sid].url)
                self.assertEqual(c["as_of"], AS_OF)

    def test_nil_exit_load(self):
        d = dict(page("hdfc-liquid"), exit_load="Nil")
        self.assertEqual(chunks_for("hdfc-liquid", d)["exit_load"]["text"],
                         "There is no exit load for HDFC Liquid Fund (Direct Growth).")

    def test_exit_load_for_units_pattern(self):
        text = ingest.exit_load_text("X Fund", "Exit Load for units in excess of 15% of the investment,"
                                               "1% will be charged for redemption within 1 year.")
        self.assertEqual(text, "For X Fund, an exit load applies to units in excess of 15% of the investment: "
                               "1% will be charged for redemption within 1 year.")

    def test_lump_sum_blocked(self):
        d = dict(page("hdfc-mid-cap"), lumpsum_allowed=False, min_investment_amount=0)
        text = chunks_for("hdfc-mid-cap", d)["min_investment"]["text"]
        self.assertIn("₹100", text)
        self.assertIn("blocked by the fund house", text)

    def test_groww_placeholder_benchmark_points_to_factsheet(self):
        d = dict(page("hdfc-mid-cap"), benchmark="GROWWEH", benchmark_name="Groww Equity Hybrid")
        c = chunks_for("hdfc-mid-cap", d)["benchmark"]
        self.assertNotIn("Groww Equity Hybrid", c["text"])
        self.assertIn("does not state an official benchmark", c["text"])
        self.assertEqual(c["source_url"], HDFC_FACTSHEET_URL)

    def test_out_of_range_values_fail(self):
        cases = [dict(expense_ratio="12.5"), dict(expense_ratio=None), dict(min_sip_investment=0),
                 dict(nav=None), dict(aum=0), dict(stamp_duty=""), dict(fund_manager_details=[], fund_manager=None)]
        for change in cases:
            with self.subTest(change=change):
                with self.assertRaises(ingest.IngestError):
                    chunks_for("hdfc-mid-cap", dict(page("hdfc-mid-cap"), **change))

    def test_objective_trimmed_to_first_sentence(self):
        d = dict(page("hdfc-mid-cap"), description="First sentence here. Second one. Third one. Fourth one.")
        text = chunks_for("hdfc-mid-cap", d)["category"]["text"]
        self.assertIn("First sentence here.", text)
        self.assertNotIn("Second one", text)


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))

    def test_committed_corpus_is_valid(self):
        self.assertEqual(ingest.validate_corpus(self.corpus), [])
        self.assertEqual(len(self.corpus["schemes"]), 27)
        self.assertTrue(330 <= len(self.corpus["chunks"]) <= 340)

    def test_committed_corpus_only_cites_allowed_sources(self):
        for c in self.corpus["chunks"]:
            if c["scheme_id"]:
                self.assertIn(c["source_url"], registry.ALLOWED_URLS | {HDFC_FACTSHEET_URL})

    def test_missing_topic_rejected(self):
        bad = copy.deepcopy(self.corpus)
        bad["chunks"] = [c for c in bad["chunks"] if c["id"] != "hdfc-mid-cap:benchmark"]
        self.assertTrue(any("missing topics benchmark" in p for p in ingest.validate_corpus(bad)))

    def test_four_sentence_chunk_rejected(self):
        bad = copy.deepcopy(self.corpus)
        bad["chunks"][0]["text"] = "One. Two. Three. Four."
        self.assertTrue(any("4 sentences" in p for p in ingest.validate_corpus(bad)))

    def test_return_figure_rejected(self):
        bad = copy.deepcopy(self.corpus)
        bad["chunks"][0]["text"] = "The 3Y return of this scheme is 16.2%."
        self.assertTrue(any("return" in p for p in ingest.validate_corpus(bad)))

    def test_judgement_word_rejected(self):
        bad = copy.deepcopy(self.corpus)
        bad["chunks"][0]["text"] = "This is a good fund with a 0.73% expense ratio."
        self.assertTrue(any("judgement" in p for p in ingest.validate_corpus(bad)))

    def test_foreign_source_rejected(self):
        bad = copy.deepcopy(self.corpus)
        bad["chunks"][0]["source_url"] = "https://www.valueresearchonline.com/x"
        self.assertTrue(any("not an allowed source" in p for p in ingest.validate_corpus(bad)))

    def test_no_return_figures_anywhere(self):
        for c in self.corpus["chunks"]:
            self.assertIsNone(RETURN_FIGURE.search(c["text"]), c["id"])

    def test_return_figure_pattern(self):
        for text in ("3Y returns 16.0%", "CAGR of 12%", "returned 8.5% in 1 year", "16% annualised",
                     "it gained 4.2% last month", "grew 30% since launch"):
            with self.subTest(text=text):
                self.assertIsNotNone(RETURN_FIGURE.search(text))
        for text in ("expense ratio is 0.73% per annum", "exit load of 1% if redeemed within 1 year",
                     "NIFTY 50 Total Return Index", "Stamp duty of 0.005%"):
            with self.subTest(text=text):
                self.assertIsNone(RETURN_FIGURE.search(text))

    def test_official_docs_valid(self):
        docs, reviewed = ingest.load_official_docs()
        self.assertEqual(len(docs), 10)
        self.assertRegex(reviewed, r"^\d{2} [A-Z][a-z]{2} \d{4}$")
        for d in docs:
            self.assertTrue(ingest._allowed_source(d["source_url"]), d["source_url"])


class TestAtomicWriteAndLock(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "corpus.json"
        self.path.write_text("OLD CONTENT", encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def test_write_replaces_content(self):
        ingest.write_atomic(self.path, "NEW")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "NEW")
        self.assertFalse(self.path.with_name("corpus.json.tmp").exists())

    def test_failure_mid_write_keeps_old_file(self):  # GAP-04
        with mock.patch.object(ingest.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                ingest.write_atomic(self.path, "NEW CONTENT")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "OLD CONTENT")
        self.assertFalse(self.path.with_name("corpus.json.tmp").exists())

    def test_lock_blocks_second_run_and_is_released(self):
        lock = Path(self.dir.name) / ".ingest.lock"
        with ingest.IngestLock(lock):
            self.assertTrue(lock.exists())
            with self.assertRaises(ingest.IngestError):
                with ingest.IngestLock(lock):
                    pass
        self.assertFalse(lock.exists())

    def test_stale_lock_is_taken_over(self):
        lock = Path(self.dir.name) / ".ingest.lock"
        lock.write_text("old", encoding="utf-8")
        old = time.time() - ingest.LOCK_STALE_SECONDS - 60
        os.utime(lock, (old, old))
        with ingest.IngestLock(lock):
            self.assertIn("pid=", lock.read_text(encoding="utf-8"))


class TestOfflineBuild(unittest.TestCase):
    def test_offline_build_from_saved_snapshots(self):
        corpus, new_snapshots, _ = ingest.build(offline=True, log=lambda *a: None)
        self.assertEqual(new_snapshots, {})
        self.assertEqual(len(corpus["schemes"]), 27)
        self.assertTrue(all(src["origin"] == "snapshot" for src in corpus["sources"].values()))
        topics = {(c["scheme_id"], c["topic"]) for c in corpus["chunks"] if c["scheme_id"]}
        self.assertEqual(len(topics), 27 * len(SCHEME_TOPICS))
        for s in registry.SCHEMES:
            for t in CORE_TOPICS:
                self.assertIn((s.id, t), topics)

    def test_main_offline_exit_code_one_and_nothing_fetched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "corpus.json"
            with mock.patch.object(ingest, "CORPUS", target), \
                 mock.patch.object(ingest, "LOCK", Path(tmp) / ".lock"), \
                 mock.patch.object(ingest, "fetch", side_effect=AssertionError("network used")), \
                 mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                code = ingest.main(["--offline"])
            self.assertEqual(code, 1)
            self.assertTrue(target.exists())

    def test_riskometer_levels_constant(self):
        self.assertEqual(len(SEBI_RISK_LEVELS), 6)


if __name__ == "__main__":
    unittest.main()
