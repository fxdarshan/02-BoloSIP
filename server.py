"""BoloSIP HTTP server and JSON API (architecture §13, §12, §17).

    python server.py            # http://127.0.0.1:8000

Standard library only (`http.server.ThreadingHTTPServer`). Every request passes, in order:
the Host check (DNS rebinding, GAP-08), the per-IP rate limit (GAP-09), then the route.
POST and DELETE also need a same-origin `Origin` (when sent) and POST needs a JSON body
(CSRF, GAP-08). Logs show method, path, status and time only, never a message (arch §17).
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from bolosip import __version__ as VERSION
from bolosip import config, guards, pipeline
from bolosip.retriever import Retriever, get_retriever
from bolosip.store import Store, ThreadNotFound

ROOT = Path(__file__).resolve().parent
INDEX_HTML = ROOT / "web" / "index.html"
SOCKET_TIMEOUT_S = 10                       # SEC-07: slow clients are dropped
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")

log = logging.getLogger("bolosip.server")


class RateLimiter:
    """Token bucket per (client IP, bucket): `per_minute` requests, refilled continuously."""

    def __init__(self, per_minute: int, clock=time.monotonic):
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str) -> tuple[bool, int]:
        """(allowed, seconds to wait if not)."""
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True, 0
            self._buckets[key] = (tokens, now)
            return False, max(1, int((1 - tokens) / self.rate + 0.999))


class ApiError(Exception):
    def __init__(self, status: int, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.headers = status, message, headers or {}


class BoloSIPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, *, store: Store, retriever: Retriever, rate_msg: int, rate_all: int,
                 extra_hosts: tuple[str, ...] = ()):
        super().__init__(address, Handler)
        self.store, self.retriever = store, retriever
        self.msg_limiter, self.all_limiter = RateLimiter(rate_msg), RateLimiter(rate_all)
        port = self.server_address[1]
        names = set(LOCAL_HOSTS) | {h for h in extra_hosts if h}
        self.allowed_hosts = {f"{h}:{port}" for h in names}
        if port == 80:
            self.allowed_hosts |= names
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}


_THREAD_PATH = "/api/threads/"


class Handler(BaseHTTPRequestHandler):
    server: BoloSIPServer
    timeout = SOCKET_TIMEOUT_S
    server_version = f"BoloSIP/{VERSION}"
    sys_version = ""

    # --- logging: method, path, status, time; never bodies or headers ---------
    def log_message(self, fmt, *args):            # silence the default access log
        pass

    def _log(self, status: int, started: float):
        path = urlsplit(self.path).path if self.path else "-"
        log.info("%s %s %d %.1f ms", self.command, path, status, (time.perf_counter() - started) * 1000)

    # --- dispatch -------------------------------------------------------------
    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_PUT(self):
        self._handle("PUT")

    def do_PATCH(self):
        self._handle("PATCH")

    def _handle(self, method: str):
        started = time.perf_counter()
        status = 500
        try:
            self._check_host()
            ok, wait = self.server.all_limiter.take(self.client_address[0])
            if not ok:
                raise ApiError(429, "Too many requests. Please wait a moment.", {"Retry-After": str(wait)})
            status = self._route(method)
        except ApiError as e:
            status = e.status
            self._json(e.status, {"error": e.message}, e.headers)
        except ThreadNotFound:
            status = 404
            self._json(404, {"error": "Thread not found"})
        except Exception as e:                       # SEC-08: type only, never details or the message
            status = 500
            log.error("internal error on %s %s: %s", method, urlsplit(self.path).path, type(e).__name__)
            try:
                self._json(500, {"error": "Internal error"})
            except Exception:
                pass
        finally:
            self._log(status, started)

    def _route(self, method: str) -> int:
        path = urlsplit(self.path).path
        if path == "/":
            self._allow(method, "GET")
            return self._index()
        if path == "/api/health":
            self._allow(method, "GET")
            return self._json(200, self._health())
        if path == "/api/config":
            self._allow(method, "GET")
            return self._json(200, {"welcome": config.WELCOME_TEXT, "examples": list(config.EXAMPLE_QUESTIONS),
                                    "disclaimer": config.DISCLAIMER, "privacy_hint": config.PRIVACY_HINT,
                                    "max_chars": config.MAX_TEXT_CHARS})
        if path == "/api/threads":
            self._allow(method, "GET", "POST")
            if method == "GET":
                return self._json(200, self.server.store.list_threads())
            self._check_write()
            self._read_json(required=False)
            t = self.server.store.create_thread()
            return self._json(201, {"id": t["id"], "title": t["title"]})
        if path.startswith(_THREAD_PATH):
            rest = path[len(_THREAD_PATH):]
            if rest.endswith("/messages"):
                tid = self._thread_id(rest[: -len("/messages")])
                self._allow(method, "GET", "POST")
                if method == "GET":
                    return self._json(200, self.server.store.get_messages(tid))
                return self._post_message(tid)
            tid = self._thread_id(rest)
            self._allow(method, "DELETE")
            self._check_write()
            if not self.server.store.delete_thread(tid):
                raise ThreadNotFound(tid)
            return self._empty(204)
        raise ApiError(404, "Not found")

    # --- endpoints ------------------------------------------------------------
    def _post_message(self, tid: str) -> int:
        self._check_write()
        body = self._read_json(required=True)
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise ApiError(400, "Body must be a JSON object with a 'text' string")
        text = text.strip()
        if not text:
            raise ApiError(400, "Message is empty")
        if len(text) > config.MAX_TEXT_CHARS:
            raise ApiError(400, f"Message too long (max {config.MAX_TEXT_CHARS})")
        ok, wait = self.server.msg_limiter.take(self.client_address[0])
        if not ok:
            raise ApiError(429, "Too many messages. Please wait a moment.", {"Retry-After": str(wait)})
        ctx = self.server.store.get_ctx(tid)               # 404 if the thread is gone
        reply, new_ctx = pipeline.handle(text, ctx, retriever=self.server.retriever)
        try:
            self.server.store.add_exchange(tid, guards.redact(text), reply, new_ctx.get("last_scheme"))
        except ThreadNotFound:
            raise
        except Exception as e:                             # THR-06: never show an unsaved reply as saved
            log.error("could not save message: %s", type(e).__name__)
            raise ApiError(500, "Could not save message") from None
        return self._json(200, reply.to_dict())

    def _health(self) -> dict:
        r = self.server.retriever
        return {"status": "ok", "version": VERSION, "llm_enabled": False, "retriever": r.backend_name(),
                "corpus_built_on": r.meta.get("built_on"), "schemes": len(r.meta.get("schemes", {}))}

    def _index(self) -> int:
        if not INDEX_HTML.is_file():
            raise ApiError(404, "The web UI arrives in Phase 6; the JSON API is under /api/")
        body = INDEX_HTML.read_bytes()
        self.send_response(200)
        self._common_headers("text/html; charset=utf-8", len(body))
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                         "form-action 'none'")
        self.end_headers()
        self.wfile.write(body)
        return 200

    # --- checks ---------------------------------------------------------------
    def _check_host(self):
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in self.server.allowed_hosts:
            raise ApiError(403, "Forbidden host")

    def _check_write(self):
        origin = self.headers.get("Origin")
        if origin is not None and origin.strip().lower() not in self.server.allowed_origins:
            raise ApiError(403, "Forbidden origin")
        if self.command == "POST":
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                raise ApiError(415, "Content-Type must be application/json")

    def _allow(self, method: str, *allowed: str):
        if method not in allowed:
            raise ApiError(405, "Method not allowed", {"Allow": ", ".join(allowed)})

    @staticmethod
    def _thread_id(raw: str) -> str:
        try:
            u = uuid.UUID(raw)
        except ValueError:
            raise ApiError(400, "Invalid thread id") from None
        if str(u) != raw.lower() or "/" in raw:
            raise ApiError(400, "Invalid thread id")
        return str(u)

    def _read_json(self, *, required: bool):
        raw_len = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(400, "Chunked bodies are not supported")
        try:
            length = int(raw_len) if raw_len is not None else 0
        except ValueError:
            raise ApiError(400, "Invalid Content-Length") from None
        if length < 0:
            raise ApiError(400, "Invalid Content-Length")
        if length > config.MAX_BODY_BYTES:
            self.close_connection = True
            raise ApiError(413, f"Request body too large (max {config.MAX_BODY_BYTES} bytes)")
        if length == 0:
            if required:
                raise ApiError(400, "Request body is empty")
            return {}
        data = self.rfile.read(length)
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Invalid JSON") from None

    # --- responses ------------------------------------------------------------
    def _common_headers(self, ctype: str, length: int):
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _json(self, status: int, payload, headers: dict | None = None) -> int:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._common_headers("application/json; charset=utf-8", len(body))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        return status

    def _empty(self, status: int) -> int:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return status


def make_server(host: str | None = None, port: int | None = None, *, store: Store | None = None,
                retriever: Retriever | None = None, rate_msg: int | None = None,
                rate_all: int | None = None) -> BoloSIPServer:
    """Build (not start) a server. Port 0 picks a free port (tests)."""
    s = config.SETTINGS
    host = s.host if host is None else host
    return BoloSIPServer(
        (host, s.port if port is None else port),
        store=store or Store(s.db_path), retriever=retriever or get_retriever(),
        rate_msg=rate_msg or s.rate_msg_per_min, rate_all=rate_all or s.rate_all_per_min,
        extra_hosts=(host.lower(),))


def main(argv: list[str] | None = None) -> int:
    from bolosip.textutil import utf8_output
    utf8_output()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = config.SETTINGS
    if s.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Listening on %s: BoloSIP has no authentication, so anyone who can reach this address "
                    "can use it (SEC-03).", s.host)
    retriever = get_retriever()                       # load the corpus and the model once, before serving
    httpd = make_server(retriever=retriever)
    log.info("BoloSIP %s on http://%s:%d (retriever: %s). %s", VERSION, s.host, httpd.server_address[1],
             retriever.backend_name(), config.DISCLAIMER)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
