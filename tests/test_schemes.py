"""Phase 3 task 1: scheme resolution (architecture §7, edge cases SCH / CTX)."""
import time
import unittest

from bolosip import registry
from bolosip.config import OTHER_AMC_NAMES
from bolosip.schemes import NON_FUND_HDFC, normalise, resolve


class TestNormalise(unittest.TestCase):
    def test_rules(self):
        cases = {
            "Large & Mid Cap": "large and mid cap",
            "mid-cap": "mid cap",
            "  MID   cap ": "mid cap",
            "ｍｉｄ ｃａｐ": "mid cap",                 # IN-15 full-width
            "mid​cap": "midcap",                # IN-16 zero-width
            "exit load of mid cap 🤔🤔": "exit load of mid cap",   # IN-14
            "Groww's rating?": "groww rating",
            "": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalise(raw), expected)


class TestRegistryNames(unittest.TestCase):
    def test_every_official_name_resolves_to_itself(self):
        for s in registry.SCHEMES:
            for text in (s.name, f"{s.name} Direct Growth", f"what is the exit load of {s.name}?"):
                with self.subTest(text=text):
                    r = resolve(text)
                    self.assertEqual((r.kind, r.scheme_ids), ("one", (s.id,)))

    def test_every_alias(self):
        index = registry.alias_index()
        for alias, ids in index.items():
            with self.subTest(alias=alias):
                r = resolve(f"what is the expense ratio of {alias}")
                if len(ids) == 1:
                    self.assertEqual((r.kind, r.scheme_ids), ("one", ids))
                else:
                    self.assertEqual(r.kind, "ambiguous")
                    self.assertEqual(set(r.scheme_ids), set(ids))


class TestConfusableGroups(unittest.TestCase):
    """Architecture §7 confusable groups and edge cases SCH-01–22: clarify, never guess."""

    def assertOne(self, text, sid):
        r = resolve(text)
        self.assertEqual((r.kind, r.scheme_ids), ("one", (sid,)), text)

    def assertAmbiguous(self, text, ids):
        r = resolve(text)
        self.assertEqual(r.kind, "ambiguous", text)
        self.assertEqual(set(r.scheme_ids), set(ids), text)

    def test_spelling_variants(self):  # SCH-02, SCH-03
        for text in ("mid cap exit load", "midcap", "mid-cap", "mid  cap", "Mid Cap"):
            self.assertOne(text, "hdfc-mid-cap")

    def test_large_and_mid_cap_wins_over_parts(self):  # SCH-04
        for text in ("large & mid cap", "large and mid cap", "Large & Mid Cap Fund exit load", "large midcap"):
            self.assertOne(text, "hdfc-large-and-mid-cap")

    def test_former_names(self):  # SCH-05, SCH-07
        self.assertOne("HDFC Equity Fund", "hdfc-flexi-cap")
        self.assertOne("HDFC Top 100 expense ratio", "hdfc-large-cap")
        self.assertOne("HDFC Mid-Cap Opportunities", "hdfc-mid-cap")
        self.assertOne("HDFC Prudence", "hdfc-balanced-advantage")
        self.assertOne("HDFC Focused 30", "hdfc-focused")

    def test_hdfc_equity_is_ambiguous(self):  # SCH-06
        self.assertAmbiguous("HDFC Equity", {"hdfc-flexi-cap", "hdfc-equity-savings"})

    def test_index_family(self):  # SCH-08, SCH-09
        self.assertAmbiguous("large cap index fund", {"hdfc-nifty-50-index", "hdfc-bse-sensex-index"})
        self.assertAmbiguous("index fund expense ratio", {"hdfc-nifty-50-index", "hdfc-bse-sensex-index"})
        self.assertOne("sensex fund", "hdfc-bse-sensex-index")
        self.assertOne("nifty 50 fund", "hdfc-nifty-50-index")
        self.assertOne("large cap", "hdfc-large-cap")

    def test_cash_like_debt(self):  # SCH-11
        self.assertOne("liquid fund", "hdfc-liquid")
        self.assertOne("money market fund", "hdfc-money-market")
        self.assertOne("overnight fund", "hdfc-overnight")
        self.assertOne("ultra short term", "hdfc-ultra-short-term")
        self.assertEqual(resolve("short term debt fund").kind, "none")

    def test_multi(self):  # SCH-12
        self.assertAmbiguous("multi exit load", {"hdfc-multi-cap", "hdfc-multi-asset-allocation"})
        self.assertAmbiguous("multi fund", {"hdfc-multi-cap", "hdfc-multi-asset-allocation"})
        self.assertOne("multi cap", "hdfc-multi-cap")
        self.assertOne("HDFC Multi Asset Allocation Fund", "hdfc-multi-asset-allocation")

    def test_several_schemes_named(self):  # SCH-13
        r = resolve("exit load of mid cap and small cap")
        self.assertEqual(r.kind, "multiple")
        self.assertEqual(set(r.scheme_ids), {"hdfc-mid-cap", "hdfc-small-cap"})

    def test_silver_vs_gold(self):  # SCH-19
        self.assertOne("silver fund", "hdfc-silver-etf-fof")
        self.assertEqual(resolve("HDFC gold fund").kind, "not_covered")
        self.assertEqual(resolve("gold fund").kind, "none")

    def test_hdfc_scheme_not_in_the_27(self):  # SCH-18
        for text in ("HDFC Gold ETF Fund of Fund expense ratio", "HDFC ELSS Tax Saver exit load",
                     "HDFC Corporate Bond Fund benchmark", "HDFC Children's Fund lock in", "hdfc tax saver"):
            with self.subTest(text=text):
                self.assertEqual(resolve(text).kind, "not_covered")
        for text in ("HDFC fund exit load", "HDFC mutual fund statement", "what is the exit load of HDFC funds",
                     "HDFC Mutual Fund factsheet", "HDFC Direct Growth plan"):
            with self.subTest(text=text):
                self.assertEqual(resolve(text).kind, "none")

    def test_weak_aliases_need_a_fund_signal(self):
        # Bare market / sector / commodity words are not scheme names on their own.
        for text in ("what is the Sensex today", "silver price today", "housing loan interest rate",
                     "what is the money market", "nifty 50 today", "infrastructure stocks to watch",
                     "gilt yields today", "what is arbitrage in trading"):
            with self.subTest(text=text):
                self.assertEqual(resolve(text).kind, "none")
        for text, sid in (("sensex fund expense ratio", "hdfc-bse-sensex-index"), ("liquid exit load", "hdfc-liquid"),
                          ("silver fof NAV", "hdfc-silver-etf-fof"), ("HDFC liquid", "hdfc-liquid"),
                          ("overnight riskometer", "hdfc-overnight"), ("defence fund manager", "hdfc-defence")):
            with self.subTest(text=text):
                self.assertOne(text, sid)

    def test_scheme_name_only(self):  # SCH-22
        self.assertOne("HDFC Mid Cap", "hdfc-mid-cap")

    def test_candidates_are_display_names(self):
        self.assertEqual(resolve("HDFC Equity").candidates, ["HDFC Flexi Cap Fund", "HDFC Equity Savings Fund"])


class TestOtherFundHouses(unittest.TestCase):
    def test_other_amc_with_matching_alias(self):  # GAP-01, SCH-16
        for text in ("SBI Small Cap exit load", "Axis Midcap TER", "Nippon India Multi Cap",
                     "ICICI Prudential Large Cap expense ratio", "Parag Parikh Flexi Cap", "Quant small cap"):
            with self.subTest(text=text):
                r = resolve(text)
                self.assertEqual(r.kind, "other_amc")
                self.assertEqual(r.scheme_ids, ())

    def test_every_listed_amc(self):
        for amc in OTHER_AMC_NAMES:
            with self.subTest(amc=amc):
                self.assertEqual(resolve(f"{amc} mid cap fund exit load").kind, "other_amc")

    def test_hdfc_named_alongside_another_amc(self):
        r = resolve("SBI and HDFC small cap exit load")
        self.assertEqual((r.kind, r.scheme_ids), ("one", ("hdfc-small-cap",)))

    def test_non_fund_hdfc_businesses(self):  # SCH-17
        for text in ("HDFC Bank share price", "HDFC Life policy", "HDFC Bank fixed deposit interest rate",
                     "HDFC Securities brokerage", "HDFC Ergo insurance"):
            with self.subTest(text=text):
                self.assertEqual(resolve(text).kind, "non_fund")
        self.assertEqual(len(NON_FUND_HDFC), len(set(NON_FUND_HDFC)))

    def test_fund_names_containing_bank_are_not_non_fund(self):
        self.assertEqual(resolve("HDFC Banking and PSU Debt Fund").scheme_ids, ("hdfc-banking-and-psu-debt",))


class TestContext(unittest.TestCase):
    def test_follow_up_uses_last_scheme(self):  # CTX-01
        r = resolve("what about its exit load", last_scheme="hdfc-mid-cap")
        self.assertEqual((r.kind, r.scheme_ids, r.via), ("one", ("hdfc-mid-cap",), "context"))
        r = resolve("and its benchmark?", last_scheme="hdfc-liquid", topic="benchmark")
        self.assertEqual(r.scheme_id, "hdfc-liquid")

    def test_no_context_means_none(self):  # CTX-02
        self.assertEqual(resolve("what is its exit load?").kind, "none")

    def test_named_scheme_overrides_context(self):  # CTX-04
        r = resolve("liquid fund exit load", last_scheme="hdfc-mid-cap")
        self.assertEqual((r.scheme_id, r.via), ("hdfc-liquid", "message"))

    def test_general_topic_ignores_context(self):  # CTX-10
        r = resolve("how do I download my statement?", last_scheme="hdfc-mid-cap", topic="statement")
        self.assertEqual(r.kind, "none")

    def test_unknown_last_scheme_ignored(self):
        self.assertEqual(resolve("its exit load", last_scheme="not-a-scheme").kind, "none")


class TestSpeed(unittest.TestCase):
    def test_resolve_is_fast(self):
        text = "what is the exit load of HDFC Large and Mid Cap Fund direct growth plan? " * 6
        start = time.perf_counter()
        for _ in range(50):
            resolve(text[:500])
        self.assertLess((time.perf_counter() - start) / 50, 0.005)


if __name__ == "__main__":
    unittest.main()
