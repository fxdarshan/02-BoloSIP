"""scripts/usage_report.py: counts from the thread database; no message text by default."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from bolosip import pipeline
from bolosip.retriever import Retriever
from bolosip.store import Store
from scripts import usage_report


class TestUsageReport(unittest.TestCase):
    def test_counts_and_privacy(self):
        r = Retriever(mode="bm25")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = Path(tmp) / "u.sqlite3"
            store = Store(db)
            tid = store.create_thread()["id"]
            ctx = {}
            for q in ("HDFC Mid Cap exit load", "weather in Mumbai", "bitcoin price", "my PAN is ABCDE1234F",
                      "HDFC Liquid Fund benchmark"):
                reply, ctx = pipeline.handle(q, ctx, retriever=r)
                store.add_exchange(tid, q, reply, ctx.get("last_scheme"))
            buf = io.StringIO()
            with redirect_stdout(buf):
                stats = usage_report.report(db)
            out = buf.getvalue()
            self.assertEqual(stats["replies"], 5)
            self.assertEqual(stats["kinds"]["answer"], 2)
            self.assertEqual(stats["kinds"]["not_found"], 2)
            self.assertEqual(stats["repeat_not_found_threads"], 1)
            self.assertEqual(stats["topics"], {"exit_load": 1, "benchmark": 1})
            self.assertNotIn("weather", out)                       # no question text by default
            self.assertNotIn("ABCDE1234F", out)
            buf = io.StringIO()
            with redirect_stdout(buf):
                usage_report.report(db, show_unanswered=True)
            self.assertIn("weather in Mumbai", buf.getvalue())
            self.assertNotIn("ABCDE1234F", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
