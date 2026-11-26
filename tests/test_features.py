"""UI feature endpoints (24-26 Nov 2026): scheme browser and fact cards, glossary terms,
rename / pin / clear-all chats and answer feedback. Each chat stays private to its browser."""
import tempfile
import unittest
from pathlib import Path

from bolosip.retriever import Retriever
from eval.api_harness import LiveServer

R = None
OTHER = {"Cookie": "bolosip_owner=" + "y" * 43}


def retriever():
    global R
    if R is None:
        R = Retriever(mode="bm25")
    return R


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.api = LiveServer(Path(self.tmp.name) / "t.sqlite3", retriever()).__enter__()

    def tearDown(self):
        self.api.__exit__(None, None, None)
        self.tmp.cleanup()


class TestSchemes(Case):
    def test_list_has_27_grouped(self):
        s, body, _ = self.api.request("GET", "/api/schemes")
        self.assertEqual((s, len(body)), (200, 27))
        groups = [x["group"] for x in body]
        self.assertEqual(groups, sorted(groups, key=["Equity", "Hybrid", "Debt", "FoF"].index))
        self.assertTrue(all({"id", "name", "group", "category"} <= set(x) for x in body))

    def test_fact_card_has_every_fact_with_source(self):
        s, card, _ = self.api.request("GET", "/api/schemes/hdfc-mid-cap")
        self.assertEqual((s, card["name"]), (200, "HDFC Mid Cap Fund"))
        self.assertEqual(len(card["facts"]), 12)
        self.assertEqual(card["facts"][0]["topic"], "expense_ratio")
        for f in card["facts"]:
            self.assertTrue(f["source"]["url"].startswith("https://"))
            self.assertTrue(f["as_of"])
        self.assertEqual(self.api.request("GET", "/api/schemes/not-a-scheme")[0], 404)
        self.assertEqual(self.api.request("GET", "/api/schemes/../threads")[0], 404)

    def test_glossary_in_config(self):
        terms = self.api.request("GET", "/api/config")[1]["terms"]
        words = {w for t in terms for w in t["words"]}
        self.assertTrue({"expense ratio", "exit load", "riskometer"} <= words)
        self.assertTrue(all(t["source"]["url"].startswith("https://") for t in terms))


class TestChatControls(Case):
    def test_rename_and_pin(self):
        a, b = self.api.new_thread(), self.api.new_thread()
        s, t, _ = self.api.request("PATCH", f"/api/threads/{a}", {"title": "  My  mid cap   notes "})
        self.assertEqual((s, t["title"]), (200, "My mid cap notes"))
        self.api.request("PATCH", f"/api/threads/{a}", {"pinned": True})
        listed = self.api.request("GET", "/api/threads")[1]
        self.assertEqual((listed[0]["id"], listed[0]["pinned"]), (a, True))          # pinned first
        self.assertIn(b, [x["id"] for x in listed])

    def test_rename_is_redacted_and_validated(self):
        a = self.api.new_thread()
        t = self.api.request("PATCH", f"/api/threads/{a}", {"title": "PAN ABCDE1234F chat"})[1]
        self.assertNotIn("ABCDE1234F", t["title"])
        for bad in ({"title": ""}, {"title": 5}, {"pinned": "yes"}, ["x"]):
            with self.subTest(body=bad):
                self.assertEqual(self.api.request("PATCH", f"/api/threads/{a}", bad)[0], 400)

    def test_other_browser_cannot_touch(self):
        a = self.api.new_thread()
        self.assertEqual(self.api.request("PATCH", f"/api/threads/{a}", {"pinned": True}, headers=OTHER)[0], 404)
        self.assertEqual(self.api.request("DELETE", "/api/threads", headers=OTHER)[0], 204)   # clears only its own
        self.assertIn(a, [x["id"] for x in self.api.request("GET", "/api/threads")[1]])

    def test_clear_all(self):
        for _ in range(3):
            self.api.new_thread()
        self.assertEqual(self.api.request("DELETE", "/api/threads")[0], 204)
        self.assertEqual(self.api.request("GET", "/api/threads")[1], [])

    def test_foreign_origin_blocked(self):
        a = self.api.new_thread()
        evil = {"Origin": "https://evil.example"}
        self.assertEqual(self.api.request("PATCH", f"/api/threads/{a}", {"title": "x"}, headers=evil)[0], 403)
        self.assertEqual(self.api.request("DELETE", "/api/threads", headers=evil)[0], 403)


class TestFeedback(Case):
    def test_thumbs(self):
        tid = self.api.new_thread()
        reply = self.api.ask(tid, "HDFC Mid Cap exit load")[1]
        mid = reply["id"]
        url = f"/api/threads/{tid}/messages/{mid}/feedback"
        self.assertEqual(self.api.request("POST", url, {"value": -1})[0], 204)
        msgs = self.api.messages(tid)
        self.assertEqual([m["feedback"] for m in msgs], [None, -1])
        self.assertEqual(self.api.request("POST", url, {"value": 0})[0], 204)
        self.assertIsNone(self.api.messages(tid)[1]["feedback"])
        for bad in ({"value": 2}, {"value": True}, {}):
            with self.subTest(body=bad):
                self.assertEqual(self.api.request("POST", url, bad)[0], 400)
        self.assertEqual(self.api.request("POST", url, {"value": 1}, headers=OTHER)[0], 404)
        user_msg = msgs[0]["id"]                                                   # only replies can be rated
        self.assertEqual(self.api.request("POST", f"/api/threads/{tid}/messages/{user_msg}/feedback",
                                          {"value": 1})[0], 404)


if __name__ == "__main__":
    unittest.main()
