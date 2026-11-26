"""Phase 5 tests: request validation and safety of the HTTP API (arch §13, §17;
edge cases IN-01–12, SEC-01–07, GAP-08, GAP-09)."""
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import server
from bolosip import config
from bolosip.retriever import Retriever
from eval.api_harness import LiveServer

R = None


def retriever():
    global R
    if R is None:
        R = Retriever(mode="bm25")
    return R


class ApiCase(unittest.TestCase):
    rate_msg = 100_000
    rate_all = 100_000

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.api = LiveServer(Path(cls.tmp.name) / "t.sqlite3", retriever(),
                             rate_msg=cls.rate_msg, rate_all=cls.rate_all).__enter__()
        cls.tid = cls.api.new_thread()

    @classmethod
    def tearDownClass(cls):
        cls.api.__exit__(None, None, None)
        cls.tmp.cleanup()

    def post_msg(self, body=None, *, raw=None, headers=None, tid=None):
        return self.api.request("POST", f"/api/threads/{tid or self.tid}/messages", body, headers, raw=raw)


class TestInputValidation(ApiCase):
    def test_empty_and_whitespace(self):                                    # IN-01, IN-02
        for text in ("", "   \n\t"):
            s, b, _ = self.post_msg({"text": text})
            self.assertEqual((s, b["error"]), (400, "Message is empty"))

    def test_length_limits(self):                                           # IN-03, IN-04
        self.assertEqual(self.post_msg({"text": "a" * 500})[0], 200)
        s, b, _ = self.post_msg({"text": "a" * 501})
        self.assertEqual((s, b["error"]), (400, "Message too long (max 500)"))

    def test_body_too_large(self):                                          # IN-05
        s, _, _ = self.post_msg(raw=b'{"text": "' + b"a" * 10_000 + b'"}',
                                headers={"Content-Type": "application/json"})
        self.assertEqual(s, 413)

    def test_invalid_json_and_wrong_shapes(self):                           # IN-06, IN-07
        self.assertEqual(self.post_msg(raw=b"{text: hi", headers={"Content-Type": "application/json"})[0], 400)
        for body in ({"text": 42}, {"msg": "hi"}, ["hi"], "hi", None):
            raw = None if body is not None else b"null"
            with self.subTest(body=body):
                s = self.post_msg(body, raw=raw, headers={"Content-Type": "application/json"} if raw else None)[0]
                self.assertEqual(s, 400)
        self.assertEqual(self.post_msg(raw=b"", headers={"Content-Type": "application/json"})[0], 400)

    def test_extra_fields_ignored(self):                                    # IN-08
        s, b, _ = self.post_msg({"text": "hi", "admin": True})
        self.assertEqual((s, b["kind"]), (200, "help"))

    def test_wrong_content_type(self):                                      # IN-09
        s, _, _ = self.post_msg(raw=b'{"text":"hi"}', headers={"Content-Type": "text/plain"})
        self.assertEqual(s, 415)
        self.assertEqual(self.post_msg(raw=b'text=hi',
                                       headers={"Content-Type": "application/x-www-form-urlencoded"})[0], 415)

    def test_thread_ids(self):                                              # IN-10, IN-11
        self.assertEqual(self.api.request("GET", "/api/threads/abc/messages")[0], 400)
        self.assertEqual(self.api.request("DELETE", "/api/threads/1234")[0], 400)
        missing = "8f14e45f-ceea-467a-9575-1c4e4a8f7f11"
        self.assertEqual(self.api.request("GET", f"/api/threads/{missing}/messages")[0], 404)
        self.assertEqual(self.post_msg({"text": "hi"}, tid=missing)[0], 404)

    def test_unknown_route_and_method(self):                                # IN-12
        self.assertEqual(self.api.request("GET", "/api/nothing")[0], 404)
        s, b, h = self.api.request("PUT", "/api/threads")
        self.assertEqual(s, 405)
        self.assertEqual(h.get("Allow"), "GET, POST, DELETE")
        self.assertEqual(self.api.request("GET", f"/api/threads/{self.tid}")[0], 405)


class TestOriginChecks(ApiCase):                                            # GAP-08, SEC-04, SEC-05
    def test_wrong_host_is_forbidden(self):
        for host in ("evil.example", f"evil.example:{self.api.port}", "127.0.0.1", "localhost:1"):
            with self.subTest(host=host):
                self.assertEqual(self.api.request("GET", "/api/health", headers={"Host": host})[0], 403)
        self.assertEqual(self.api.request("GET", "/api/health", headers={"Host": f"localhost:{self.api.port}"})[0], 200)

    def test_foreign_origin_blocked_on_writes(self):
        for origin in ("https://evil.example", "null", f"http://evil.example:{self.api.port}"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post_msg({"text": "hi"}, headers={"Origin": origin})[0], 403)
                self.assertEqual(self.api.request("POST", "/api/threads", {}, {"Origin": origin})[0], 403)
                self.assertEqual(self.api.request("DELETE", f"/api/threads/{self.tid}", headers={"Origin": origin})[0], 403)
        own = f"http://127.0.0.1:{self.api.port}"
        self.assertEqual(self.post_msg({"text": "hi"}, headers={"Origin": own})[0], 200)

    def test_no_cors_headers(self):
        _, _, headers = self.api.request("GET", "/api/health", headers={"Origin": "https://evil.example"})
        self.assertFalse(any(k.lower().startswith("access-control-") for k in headers))
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")


class TestSecurity(ApiCase):
    def test_path_traversal(self):                                          # SEC-01, SEC-10
        for path in ("/../../ingest.py", "/%2e%2e/%2e%2e/ingest.py", "/web/../server.py", "/data/raw/fetched.json",
                     "/.env", "/server.py"):
            with self.subTest(path=path):
                self.assertEqual(self.api.request("GET", path)[0], 404)

    def test_health_and_config(self):
        s, b, _ = self.api.request("GET", "/api/health")
        self.assertEqual((s, b["status"], b["schemes"]), (200, "ok", 27))     # exit criterion
        self.assertIn("llm_enabled", b)
        s, b, _ = self.api.request("GET", "/api/config")
        self.assertEqual(b["examples"], list(config.EXAMPLE_QUESTIONS))
        self.assertEqual(b["disclaimer"], "Facts-only. No investment advice.")

    def test_data_age(self):                                                 # Phase 7
        import datetime as dt
        self.assertEqual(server.data_age_days("20 Nov 2026", dt.date(2026, 11, 22)), 2)
        self.assertIsNone(server.data_age_days("not a date"))
        b = self.api.request("GET", "/api/health")[1]
        self.assertIn("data_age_days", b)
        self.assertGreaterEqual(b["data_age_days"], 0)

    def test_logs_have_no_message_text(self):                               # arch §17
        self.post_msg({"text": "secret words about HDFC Mid Cap exit load"})
        logs = self.api.log.getvalue()
        self.assertIn("POST /api/threads/", logs)
        self.assertNotIn("secret words", logs)

    def test_internal_errors_hide_details(self):                            # SEC-08
        with mock.patch.object(server.pipeline, "handle", side_effect=RuntimeError("key=gsk_SECRET")):
            s, b, _ = self.post_msg({"text": "HDFC Mid Cap exit load"})
        self.assertEqual((s, b["error"]), (500, "Internal error"))
        self.assertNotIn("gsk_SECRET", self.api.log.getvalue())

    def test_save_failure_is_reported(self):                                # THR-06
        with mock.patch.object(self.api.store, "add_exchange", side_effect=OSError("disk full")):
            s, b, _ = self.post_msg({"text": "HDFC Mid Cap exit load"})
        self.assertEqual((s, b["error"]), (500, "Could not save message"))

    def test_slow_client_is_dropped(self):                                  # SEC-07
        with mock.patch.object(server.Handler, "timeout", 1):
            with socket.create_connection(("127.0.0.1", self.api.port), timeout=5) as sock:
                sock.sendall(b"POST /api/threads HTTP/1.1\r\nHost: 127.0.0.1\r\n")    # never finishes
                start = time.monotonic()
                sock.settimeout(5)
                try:
                    data = sock.recv(1024)
                except (ConnectionResetError, socket.timeout):
                    data = b""
                self.assertLess(time.monotonic() - start, 4)
                self.assertEqual(data, b"")

    def test_public_bind_warns(self):                                       # SEC-03
        with mock.patch.object(server.config, "SETTINGS", config.load_settings({"BOLOSIP_HOST": "0.0.0.0"})), \
                mock.patch.object(server, "make_server", side_effect=KeyboardInterrupt), \
                mock.patch.object(server, "get_retriever", return_value=retriever()), \
                self.assertLogs("bolosip.server", "WARNING") as cm:
            try:
                server.main()
            except KeyboardInterrupt:
                pass
        self.assertIn("no authentication", "\n".join(cm.output))


class TestRateLimit(ApiCase):                                               # GAP-09, SEC-06
    rate_msg = 30
    rate_all = 120

    def test_31st_message_in_a_minute_is_refused(self):
        statuses = [self.post_msg({"text": "hi"})[0] for _ in range(31)]
        self.assertEqual(statuses[:30], [200] * 30)
        s, b, h = self.post_msg({"text": "hi"})
        self.assertEqual(s, 429)
        self.assertGreaterEqual(int(h["Retry-After"]), 1)

    def test_bucket_refills(self):
        now = [0.0]
        rl = server.RateLimiter(30, clock=lambda: now[0])
        self.assertTrue(all(rl.take("ip")[0] for _ in range(30)))
        self.assertEqual(rl.take("ip"), (False, 2))
        now[0] += 2.0
        self.assertTrue(rl.take("ip")[0])
        self.assertTrue(rl.take("other-ip")[0])                              # per IP


class TestLatency(ApiCase):
    def test_extractive_latency(self):                                      # eval.md Phase 5
        qs = ["HDFC Mid Cap expense ratio", "its exit load", "HDFC Liquid Fund benchmark", "hi"]
        for q in qs:                                                        # warm-up
            self.post_msg({"text": q})
        times = []
        for q in qs * 10:
            start = time.perf_counter()
            self.assertEqual(self.post_msg({"text": q})[0], 200)
            times.append((time.perf_counter() - start) * 1000)
        times.sort()
        # Regression bound only: shared CI runners are too noisy for the eval.md target
        # (p50 < 50 ms, p95 < 150 ms), which the Phase 5 gate enforces on local runs.
        self.assertLess(times[len(times) // 2], 250)


if __name__ == "__main__":
    unittest.main()
