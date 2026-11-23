"""Hosting tests (Doc/deployment-plan.md §3, blockers B1-B8): chats belong to one browser,
the public host name and Railway's healthcheck are allowed, the visitor's IP comes from the
proxy only when trusted, HTTPS headers, settings, and a clean stop on SIGTERM."""
import signal
import tempfile
import threading
import unittest
from pathlib import Path

import server
from bolosip import config
from bolosip.retriever import Retriever
from eval.api_harness import LiveServer

R = None
PUBLIC = "bolosip.up.railway.app"


def retriever():
    global R
    if R is None:
        R = Retriever(mode="bm25")
    return R


class Case(unittest.TestCase):
    server_kwargs: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.api = LiveServer(Path(cls.tmp.name) / "t.sqlite3", retriever(), **cls.server_kwargs).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.api.__exit__(None, None, None)
        cls.tmp.cleanup()


class TestSettings(unittest.TestCase):
    def test_port_from_the_platform_wins(self):                              # B2
        self.assertEqual(config.load_settings({}).port, 8000)
        self.assertEqual(config.load_settings({"BOLOSIP_PORT": "9000"}).port, 9000)
        self.assertEqual(config.load_settings({"BOLOSIP_PORT": "9000", "PORT": "7123"}).port, 7123)
        with self.assertRaises(ValueError):
            config.load_settings({"PORT": "abc"})

    def test_public_hosts(self):                                             # B3
        s = config.load_settings({"BOLOSIP_PUBLIC_HOSTS": " https://A.example/ , b.example:443,a.example"})
        self.assertEqual(s.public_hosts, ("a.example", "b.example"))
        self.assertEqual(config.load_settings({"RAILWAY_PUBLIC_DOMAIN": PUBLIC}).public_hosts, (PUBLIC,))
        self.assertEqual(config.load_settings({}).public_hosts, ())

    def test_flags_and_retention(self):                                      # B4, B7
        self.assertFalse(config.load_settings({}).trust_proxy)
        self.assertTrue(config.load_settings({"BOLOSIP_TRUST_PROXY": "1"}).trust_proxy)
        with self.assertRaises(ValueError):
            config.load_settings({"BOLOSIP_TRUST_PROXY": "maybe"})
        self.assertEqual(config.load_settings({}).retention_days, 0)
        self.assertEqual(config.load_settings({"BOLOSIP_RETENTION_DAYS": "30"}).retention_days, 30)


class TestOwnership(Case):                                                   # B1
    def test_cookie_is_set_once_with_safe_flags(self):
        s, _, h = self.api.request("GET", "/", cookies=False)
        self.assertEqual(s, 200)
        cookie = h["Set-Cookie"]
        self.assertRegex(cookie, r"^bolosip_owner=[A-Za-z0-9_-]{43}; ")
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, cookie)
        self.assertNotIn("Secure", cookie)                                   # plain http on the laptop
        token = cookie.split(";", 1)[0]
        self.assertNotIn("Set-Cookie", self.api.request("GET", "/api/health", headers={"Cookie": token})[2])

    def test_another_browser_cannot_see_or_touch_a_chat(self):
        tid = self.api.new_thread()
        self.api.ask(tid, "HDFC Mid Cap exit load")
        mine = [t["id"] for t in self.api.request("GET", "/api/threads")[1]]
        self.assertIn(tid, mine)
        other = {"Cookie": "bolosip_owner=" + "x" * 43}
        self.assertEqual(self.api.request("GET", "/api/threads", headers=other)[1], [])
        self.assertEqual(self.api.request("GET", f"/api/threads/{tid}/messages", headers=other)[0], 404)
        self.assertEqual(self.api.request("POST", f"/api/threads/{tid}/messages", {"text": "hi"},
                                          headers=other)[0], 404)
        self.assertEqual(self.api.request("DELETE", f"/api/threads/{tid}", headers=other)[0], 404)
        self.assertEqual(len(self.api.messages(tid)), 2)                     # untouched for its owner

    def test_bad_cookie_gets_a_new_owner(self):
        for bad in ("bolosip_owner=short", "bolosip_owner=" + "!" * 43, '"; =;', "other=1"):
            with self.subTest(cookie=bad):
                s, body, h = self.api.request("GET", "/api/threads", headers={"Cookie": bad})
                self.assertEqual((s, body), (200, []))
                self.assertIn("Set-Cookie", h)

    def test_the_token_is_not_stored(self):
        self.api.new_thread()
        token = self.api.cookie.split("=", 1)[1]
        raw = b"".join(p.read_bytes() for p in Path(self.tmp.name).glob("t.sqlite3*"))
        self.assertNotIn(token.encode(), raw)


class TestPublicServer(Case):                                                # B3, B4, B6
    server_kwargs = {"public_hosts": (PUBLIC,), "trust_proxy": True, "rate_msg": 2}
    edge = {"Host": PUBLIC, "X-Forwarded-Proto": "https"}

    def test_public_host_and_https_origin(self):
        self.assertEqual(self.api.request("GET", "/api/health", headers=self.edge)[0], 200)
        hdr = {**self.edge, "Origin": f"https://{PUBLIC}"}
        s, body, _ = self.api.request("POST", "/api/threads", {}, hdr)
        self.assertEqual(s, 201)
        self.assertEqual(self.api.request("POST", "/api/threads", {}, {**self.edge, "Origin": f"http://{PUBLIC}"})[0], 403)
        self.assertEqual(self.api.request("GET", "/api/health", headers={"Host": "evil.example"})[0], 403)

    def test_healthcheck_host_only_for_health(self):
        hc = {"Host": server.HEALTHCHECK_HOST}
        self.assertEqual(self.api.request("GET", "/api/health", headers=hc)[0], 200)
        self.assertEqual(self.api.request("GET", "/api/threads", headers=hc)[0], 403)
        self.assertEqual(self.api.request("GET", "/", headers=hc)[0], 403)

    def test_https_headers(self):
        _, _, h = self.api.request("GET", "/", headers=self.edge, cookies=False)
        self.assertIn("Secure", h["Set-Cookie"])
        self.assertEqual(h["Strict-Transport-Security"], "max-age=31536000")
        _, _, h = self.api.request("GET", "/api/health", headers={"Host": PUBLIC}, cookies=False)
        self.assertNotIn("Strict-Transport-Security", h)                    # not via https

    def test_rate_limit_is_per_visitor(self):
        tid = self.api.request("POST", "/api/threads", {}, self.edge)[1]["id"]
        def ask(ip):
            return self.api.request("POST", f"/api/threads/{tid}/messages", {"text": "hi"},
                                    {**self.edge, "X-Real-IP": ip})[0]
        self.assertEqual([ask("203.0.113.7") for _ in range(3)], [200, 200, 429])
        self.assertEqual(ask("198.51.100.9"), 200)                           # another visitor

    def test_public_server_does_not_hand_out_old_chats(self):
        self.api.store.create_thread()                                       # owner NULL, as before B1
        self.assertEqual(self.api.request("GET", "/api/threads", headers=self.edge, cookies=False)[1], [])


class TestProxyHeadersIgnoredLocally(Case):                                  # B4
    server_kwargs = {"rate_msg": 2}

    def test_x_real_ip_cannot_dodge_the_limit(self):
        tid = self.api.new_thread()
        statuses = [self.api.request("POST", f"/api/threads/{tid}/messages", {"text": "hi"},
                                     {"X-Real-IP": f"10.0.0.{i}"})[0] for i in range(3)]
        self.assertEqual(statuses, [200, 200, 429])
        _, _, h = self.api.request("GET", "/", headers={"X-Forwarded-Proto": "https"}, cookies=False)
        self.assertNotIn("Strict-Transport-Security", h)
        self.assertNotIn("Secure", h["Set-Cookie"])


class TestShutdown(unittest.TestCase):                                       # B5
    def test_sigterm_stops_the_server(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            api = LiveServer(Path(tmp) / "t.sqlite3", retriever()).__enter__()
            previous = signal.getsignal(signal.SIGTERM)
            stopped = threading.Event()
            try:
                server._install_sigterm(api.httpd, stopped)
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                api._thread.join(5)
                self.assertFalse(api._thread.is_alive())
                self.assertTrue(stopped.is_set())
                self.assertTrue(api.httpd.wait_idle(1))
            finally:
                signal.signal(signal.SIGTERM, previous)
                api.httpd.server_close()

    def test_wait_idle_times_out_while_busy(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with LiveServer(Path(tmp) / "t.sqlite3", retriever()) as api:
                api.httpd.track(+1)
                self.assertFalse(api.httpd.wait_idle(0.2))
                api.httpd.track(-1)
                self.assertTrue(api.httpd.wait_idle(0.2))


if __name__ == "__main__":
    unittest.main()
