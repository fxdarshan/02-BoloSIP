"""Run the real HTTP server in-process on a free port, for tests and the Phase 5 gate.

    with LiveServer(db_path, retriever) as api:
        tid = api.new_thread()
        status, reply = api.ask(tid, "HDFC Mid Cap exit load")

Requests go over a real socket (http.client), so Host / Origin / Content-Type checks,
body limits and status codes are exercised exactly as a browser would hit them.
"""
from __future__ import annotations

import http.client
import io
import json
import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from bolosip.store import Store  # noqa: E402


class LiveServer:
    def __init__(self, db_path: Path, retriever, *, rate_msg: int = 100_000, rate_all: int = 100_000,
                 capture_logs: bool = True):
        self.db_path = Path(db_path)
        self.retriever = retriever
        self.rate_msg, self.rate_all = rate_msg, rate_all
        self.capture_logs = capture_logs
        self.log = io.StringIO()

    def __enter__(self):
        self.store = Store(self.db_path)
        self.httpd = server.make_server("127.0.0.1", 0, store=self.store, retriever=self.retriever,
                                        rate_msg=self.rate_msg, rate_all=self.rate_all)
        self.port = self.httpd.server_address[1]
        if self.capture_logs:
            self._handler = logging.StreamHandler(self.log)
            self._handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
            lg = logging.getLogger("bolosip.server")
            lg.addHandler(self._handler)
            lg.setLevel(logging.INFO)
            lg.propagate = False
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.capture_logs:
            lg = logging.getLogger("bolosip.server")
            lg.removeHandler(self._handler)
            lg.propagate = True

    # --- raw requests -----------------------------------------------------------
    def request(self, method: str, path: str, body=None, headers: dict | None = None, *, raw: bytes | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {}
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        skip_host = "Host" in h
        conn.putrequest(method, path, skip_host=skip_host, skip_accept_encoding=True)
        for k, v in h.items():
            conn.putheader(k, v)
        if data is not None and "Content-Length" not in h:
            conn.putheader("Content-Length", str(len(data)))
        conn.endheaders(data)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        ctype = resp.getheader("Content-Type") or ""
        parsed = json.loads(payload) if payload and ctype.startswith("application/json") else payload
        return resp.status, parsed, dict(resp.getheaders())

    # --- helpers ----------------------------------------------------------------
    def new_thread(self) -> str:
        status, body, _ = self.request("POST", "/api/threads", {})
        assert status == 201, (status, body)
        return body["id"]

    def ask(self, thread_id: str, text: str):
        status, body, _ = self.request("POST", f"/api/threads/{thread_id}/messages", {"text": text})
        return status, body

    def messages(self, thread_id: str):
        return self.request("GET", f"/api/threads/{thread_id}/messages")[1]
