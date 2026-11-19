"""Phase 5 tests: threads, storage and concurrency over the real HTTP server (arch §5.3, §12).

Offline, BM25 retriever, a temporary SQLite file per test class.
"""
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bolosip import config
from bolosip.retriever import Retriever
from bolosip.store import NEW_TITLE, Store, ThreadNotFound
from eval.api_harness import LiveServer
from eval.answer_eval import check_reply

DATASETS = config.ROOT / "eval" / "datasets"
RETRIEVER = None


def retriever():
    global RETRIEVER
    if RETRIEVER is None:
        RETRIEVER = Retriever(mode="bm25")
    return RETRIEVER


def load(name):
    return [json.loads(x) for x in (DATASETS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db = Path(cls.tmp.name) / "threads.sqlite3"
        cls.api = LiveServer(cls.db, retriever()).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.api.__exit__(None, None, None)
        cls.tmp.cleanup()


class TestThreads(ServerCase):
    def test_interleaved_threads_keep_their_own_scheme(self):               # AC 7
        a, b = self.api.new_thread(), self.api.new_thread()
        self.assertEqual(self.api.ask(a, "HDFC Mid Cap Fund expense ratio")[1]["scheme_id"], "hdfc-mid-cap")
        self.assertEqual(self.api.ask(b, "HDFC Liquid Fund benchmark")[1]["scheme_id"], "hdfc-liquid")
        ra = self.api.ask(a, "what is its exit load?")[1]
        rb = self.api.ask(b, "what is its exit load?")[1]
        self.assertEqual((ra["scheme_id"], rb["scheme_id"]), ("hdfc-mid-cap", "hdfc-liquid"))
        self.assertIn("HDFC Mid Cap", ra["text"])
        self.assertIn("HDFC Liquid", rb["text"])

    def test_context_does_not_leak_to_a_new_thread(self):                   # CTX-09
        a = self.api.new_thread()
        self.api.ask(a, "HDFC Mid Cap exit load")
        b = self.api.new_thread()
        self.assertEqual(self.api.ask(b, "what is its exit load?")[1]["kind"], "clarify")

    def test_history_titles_and_listing(self):
        t = self.api.new_thread()
        listed = self.api.request("GET", "/api/threads")[1]
        self.assertEqual([x["title"] for x in listed if x["id"] == t], [NEW_TITLE])        # THR-09
        self.api.ask(t, "Should I invest in HDFC Mid Cap?")                                # THR-10
        self.api.ask(t, "HDFC Mid Cap exit load")
        msgs = self.api.messages(t)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"] * 2)
        self.assertEqual(msgs[1]["kind"], "refusal")
        self.assertTrue(msgs[3]["source"]["url"].startswith("https://groww.in/"))
        self.assertTrue(msgs[3]["footer"].startswith("Last updated from sources: "))
        listed = self.api.request("GET", "/api/threads")[1]
        self.assertEqual(listed[0]["id"], t)                                     # newest first
        self.assertEqual(listed[0]["title"], "Should I invest in HDFC Mid Cap?")

    def test_clarify_candidates_are_kept_in_history(self):
        t = self.api.new_thread()
        self.api.ask(t, "HDFC Equity expense ratio")
        self.assertEqual(set(self.api.messages(t)[1]["candidates"]), {"HDFC Flexi Cap Fund", "HDFC Equity Savings Fund"})

    def test_delete_removes_messages(self):
        t = self.api.new_thread()
        self.api.ask(t, "HDFC Gilt Fund exit load")
        self.assertEqual(self.api.request("DELETE", f"/api/threads/{t}")[0], 204)
        self.assertEqual(self.api.request("GET", f"/api/threads/{t}/messages")[0], 404)
        self.assertEqual(self.api.ask(t, "exit load?")[0], 404)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM messages WHERE thread_id = ?", (t,)).fetchone()[0], 0)

    def test_sql_injection_is_just_text(self):                               # SEC-02
        t = self.api.new_thread()
        status, reply = self.api.ask(t, "'; DROP TABLE threads;--")
        self.assertEqual(status, 200)
        self.assertEqual(self.api.messages(t)[0]["text"], "'; DROP TABLE threads;--")
        self.assertEqual(self.api.request("GET", "/api/threads")[0], 200)


class TestPrivacyStorage(ServerCase):
    def test_no_personal_data_value_reaches_the_database_or_logs(self):     # AC 6, PII hard gate
        t = self.api.new_thread()
        positives = [c for c in load("pii") if c["expect"]["kind"] == "privacy"]
        for c in positives:
            status, reply = self.api.ask(t, c["question"])
            self.assertEqual((status, reply["kind"]), (200, "privacy"), c["id"])
        # Also as the first message of a thread: the title is redacted too.
        t2 = self.api.new_thread()
        self.api.ask(t2, "my PAN is ABCDE1234F and phone 9876543210")
        from eval.pii_scan import leaked_values
        values = [v for c in positives for v in c["expect"].get("values", [])]
        self.assertGreater(len(values), 30)
        self.assertEqual(leaked_values(self.db, values, self.api.log.getvalue()), [])
        # The scan itself works: an unredacted value would be found.
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE messages SET text = 'aadhaar ending 4567' WHERE id = (SELECT MIN(id) FROM messages)")
        self.assertEqual(leaked_values(self.db, ["4567"]), ["4567"])
        self.assertIn("[redacted]", self.api.request("GET", "/api/threads")[1][0]["title"])

    def test_store_redacts_even_if_the_caller_forgets(self):
        store = Store(Path(self.tmp.name) / "direct.sqlite3")
        t = store.create_thread()["id"]
        from bolosip.formatter import make
        store.add_exchange(t, "my PAN is ABCDE1234F", make("help", "Hi."), None)
        self.assertNotIn("ABCDE1234F", json.dumps(store.get_messages(t)))
        self.assertNotIn(b"ABCDE1234F", (Path(self.tmp.name) / "direct.sqlite3").read_bytes())


class TestConcurrency(ServerCase):
    def test_parallel_requests_across_threads(self):                        # THR-03
        questions = ["HDFC Mid Cap expense ratio", "its exit load", "its benchmark", "its riskometer"]
        for _round in range(3):
            tids = [self.api.new_thread() for _ in range(5)]
            # Within a thread the UI sends one message at a time; threads run in parallel.
            def run(tid):
                return [self.api.ask(tid, q) for q in questions]
            with ThreadPoolExecutor(max_workers=20) as pool:
                results = list(pool.map(run, tids))
            for tid, res in zip(tids, results):
                self.assertTrue(all(s == 200 for s, _ in res))
                self.assertTrue(all(r["scheme_id"] == "hdfc-mid-cap" for _, r in res))
                msgs = self.api.messages(tid)
                self.assertEqual([m["text"] for m in msgs if m["role"] == "user"], questions)

    def test_twenty_parallel_messages_in_one_thread(self):                 # THR-01
        t = self.api.new_thread()
        with ThreadPoolExecutor(max_workers=20) as pool:
            statuses = list(pool.map(lambda i: self.api.ask(t, f"HDFC Liquid Fund exit load {i}")[0], range(20)))
        self.assertEqual(statuses, [200] * 20)
        self.assertEqual(len(self.api.messages(t)), 40)

    def test_delete_during_requests_leaves_no_orphans(self):               # THR-02
        t = self.api.new_thread()
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(self.api.ask, t, "HDFC Gilt Fund benchmark") for _ in range(10)]
            self.api.request("DELETE", f"/api/threads/{t}")
            statuses = {f.result()[0] for f in futures}
        self.assertLessEqual(statuses, {200, 404})
        with sqlite3.connect(self.db) as c:
            orphans = c.execute("SELECT COUNT(*) FROM messages m LEFT JOIN threads t ON m.thread_id = t.id "
                                "WHERE t.id IS NULL").fetchone()[0]
        self.assertEqual(orphans, 0)


class TestPersistence(unittest.TestCase):
    def test_history_and_context_survive_a_restart(self):                  # THR-11, CTX-11
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = Path(tmp) / "t.sqlite3"
            with LiveServer(db, retriever()) as api:
                t = api.new_thread()
                api.ask(t, "HDFC Small Cap Fund expense ratio")
            with LiveServer(db, retriever()) as api:
                self.assertEqual(len(api.messages(t)), 2)
                reply = api.ask(t, "what about its exit load?")[1]
                self.assertEqual(reply["scheme_id"], "hdfc-small-cap")

    def test_deleted_database_is_recreated(self):                           # THR-05
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = Path(tmp) / "t.sqlite3"
            store = Store(db)
            for p in Path(tmp).iterdir():
                p.unlink()
            self.assertEqual(store.list_threads(), [])
            self.assertTrue(db.exists())

    def test_unknown_thread(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = Store(Path(tmp) / "t.sqlite3")
            with self.assertRaises(ThreadNotFound):
                store.get_ctx("00000000-0000-4000-8000-000000000000")


class TestConversationsOverHttp(ServerCase):
    def test_conversations(self):                                           # AC 7 over HTTP
        for conv in load("conversations"):
            t = self.api.new_thread()
            for i, turn in enumerate(conv["turns"]):
                status, body = self.api.ask(t, turn["q"])
                if turn["expect"].get("dense_only"):
                    continue
                with self.subTest(id=conv["id"], turn=i, q=turn["q"]):
                    self.assertEqual(status, 200)
                    self.assertEqual(_check(body, turn["expect"]), [])


def _check(body, expect):
    from bolosip.formatter import Reply, Source
    reply = Reply(body["kind"], body["text"], Source(**body["source"]) if body["source"] else None,
                  body["footer"], body["scheme_id"], tuple(body["candidates"]) if body["candidates"] is not None else None)
    return check_reply(retriever(), reply, expect)


if __name__ == "__main__":
    unittest.main()
