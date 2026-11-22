"""scripts/data_diff.py: the daily refresh's change report and blocking rules (Phase 7)."""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bolosip import config
from scripts import data_diff

CORPUS = json.loads(config.SETTINGS.corpus_path.read_text(encoding="utf-8"))


def chunk(corpus, cid):
    return next(c for c in corpus["chunks"] if c["id"] == cid)


def next_day(corpus):
    """The same corpus as it would look tomorrow: new dates, NAV and fund size."""
    new = copy.deepcopy(corpus)
    new["built_on"] = "01 Jan 2099"
    for c in new["chunks"]:
        c["as_of"] = "01 Jan 2099"
        if c["topic"] == "nav":
            c["text"] = c["text"].split("₹")[0] + "₹123.456 as on 31 Dec 2098."
        if c["topic"] == "aum":
            c["text"] = c["text"].split("₹")[0] + "₹9,876.54 crore."
    return new


class TestCompare(unittest.TestCase):
    def test_unchanged_corpus(self):
        rep = data_diff.compare(CORPUS, copy.deepcopy(CORPUS))
        self.assertFalse(rep.file_changed)
        self.assertEqual((rep.facts_changed, rep.blocked_reasons), (0, []))

    def test_daily_values_are_expected(self):
        rep = data_diff.compare(CORPUS, next_day(CORPUS))
        self.assertTrue(rep.file_changed)
        self.assertEqual(len(rep.daily), 54)                      # 27 NAV + 27 fund size
        self.assertEqual((rep.stable, rep.minor, rep.blocked_reasons), ([], [], []))

    def test_small_expense_ratio_move_is_minor(self):
        new = next_day(CORPUS)
        er = chunk(new, "hdfc-mid-cap:expense_ratio")
        er["text"] = er["text"].replace("0.73%", "0.75%")
        rep = data_diff.compare(CORPUS, new)
        self.assertEqual([r[0] for r in rep.minor], ["hdfc-mid-cap:expense_ratio"])
        self.assertEqual(rep.stable, [])

    def test_large_expense_ratio_move_is_stable(self):
        new = next_day(CORPUS)
        er = chunk(new, "hdfc-mid-cap:expense_ratio")
        er["text"] = er["text"].replace("0.73%", "1.73%")
        rep = data_diff.compare(CORPUS, new)
        self.assertEqual([r[0] for r in rep.stable], ["hdfc-mid-cap:expense_ratio"])
        self.assertEqual(rep.blocked_reasons, [])                 # one change is reported, not blocked

    def test_more_than_five_stable_changes_block(self):
        new = next_day(CORPUS)
        schemes = [s for s in sorted({c["scheme_id"] for c in new["chunks"] if c["scheme_id"]})][:6]
        for sid in schemes:
            c = chunk(new, f"{sid}:benchmark")
            c["text"] = c["text"].replace("Index", "Indicator")
        rep = data_diff.compare(CORPUS, new)
        self.assertEqual(len(rep.stable), 6)
        self.assertIn("6 stable facts changed", rep.blocked_reasons[0])

    def test_missing_scheme_blocks(self):
        new = next_day(CORPUS)
        new["chunks"] = [c for c in new["chunks"] if c["scheme_id"] != "hdfc-gilt"]
        rep = data_diff.compare(CORPUS, new)
        self.assertEqual(rep.missing_schemes, ["hdfc-gilt"])
        self.assertTrue(rep.blocked_reasons)

    def test_snapshot_schemes_are_listed(self):
        new = next_day(CORPUS)
        new["sources"]["hdfc-liquid"]["origin"] = "snapshot"
        for sid in new["sources"]:
            if sid != "hdfc-liquid":
                new["sources"][sid]["origin"] = "live"
        self.assertEqual(data_diff.compare(CORPUS, new).snapshot_schemes, ["hdfc-liquid"])


class TestCli(unittest.TestCase):
    def test_outputs_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            old, new, summary, out = tmp / "old.json", tmp / "new.json", tmp / "summary.md", tmp / "out.txt"
            old.write_text(json.dumps(CORPUS), encoding="utf-8")
            new.write_text(json.dumps(next_day(CORPUS)), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = data_diff.main([str(old), str(new), "--summary", str(summary), "--github-output", str(out)])
            self.assertEqual(code, 0)
            outputs = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
            self.assertEqual((outputs["changed"], outputs["blocked"], outputs["stable_changes"]), ("true", "false", "0"))
            self.assertEqual(outputs["facts_changed"], "54")
            self.assertIn("Verdict: OK to commit", summary.read_text(encoding="utf-8"))
            broken = next_day(CORPUS)
            broken["chunks"] = [c for c in broken["chunks"] if c["scheme_id"] != "hdfc-gilt"]
            new.write_text(json.dumps(broken), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(data_diff.main([str(old), str(new)]), 3)


if __name__ == "__main__":
    unittest.main()
