"""BoloSIP HTTP server and JSON API (architecture §13, §12, §17).

    python server.py            # http://127.0.0.1:8000

Standard library only (`http.server.ThreadingHTTPServer`). Every request passes, in order:
the Host check (DNS rebinding, GAP-08), the per-IP rate limit (GAP-09), then the route.
POST and DELETE also need a same-origin `Origin` (when sent) and POST needs a JSON body
(CSRF, GAP-08). Logs show method, path, status and time only, never a message (arch §17).

Hosting (Doc/deployment-plan.md §3): each browser gets a random owner token in an HttpOnly
cookie and sees only its own chats (B1); `PORT`, `BOLOSIP_PUBLIC_HOSTS` and
`BOLOSIP_TRUST_PROXY` let it run behind Railway's HTTPS edge (B2-B4, B6); SIGTERM stops it
cleanly (B5); `BOLOSIP_RETENTION_DAYS` deletes old chats (B7).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import secrets
import signal
import socket
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from bolosip import __version__ as VERSION
from bolosip import config, guards, llm, pipeline, registry, suggest
from bolosip.topics import TOPIC_LABELS
from bolosip.retriever import Retriever, get_retriever
from bolosip.store import FEEDBACK_REASONS, Store, ThreadNotFound

ROOT = Path(__file__).resolve().parent
INDEX_HTML = ROOT / "web" / "index.html"
SOCKET_TIMEOUT_S = 10                       # SEC-07: slow clients are dropped
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")
OWNER_COOKIE = "bolosip_owner"
OWNER_COOKIE_MAX_AGE = 400 * 24 * 3600      # the longest browsers keep a cookie
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")  # secrets.token_urlsafe(32)
HEALTHCHECK_HOST = "healthcheck.railway.app"  # Railway's deploy-time healthcheck sends this Host
SHUTDOWN_GRACE_S = 8                        # Railway's draining time is set to 10 s
RETENTION_SWEEP_S = 24 * 3600

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
    # socketserver's default listen backlog is 5: a burst of 20 parallel requests (THR-03)
    # had connections reset on Linux before a handler thread could accept them.
    request_queue_size = 128

    def __init__(self, address, *, store: Store, retriever: Retriever, rate_msg: int, rate_all: int,
                 extra_hosts: tuple[str, ...] = (), public_hosts: tuple[str, ...] = (),
                 trust_proxy: bool = False, rephrase=None):
        if ":" in address[0]:                       # an IPv6 address such as "::" (B2)
            self.address_family = socket.AF_INET6
        super().__init__(address, Handler)
        self.store, self.retriever = store, retriever
        self.rephrase = rephrase                    # Phase 8: Groq rewording, or None (extractive)
        self.msg_limiter, self.all_limiter = RateLimiter(rate_msg), RateLimiter(rate_all)
        self.trust_proxy = trust_proxy
        self.public = bool(public_hosts)
        port = self.server_address[1]
        names = set(LOCAL_HOSTS) | {h for h in extra_hosts if h}
        self.allowed_hosts = {f"{h}:{port}" for h in names}
        if port == 80:
            self.allowed_hosts |= names
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}
        # Public names arrive through the HTTPS edge: no port in Host, https:// in Origin (B3).
        pub = {h.lower() for h in public_hosts if h}
        self.allowed_hosts |= pub | {f"{h}:{port}" for h in pub}
        self.allowed_origins |= {f"https://{h}" for h in pub}
        self._active = 0                            # requests in flight, for a clean stop (B5)
        self._active_lock = threading.Lock()

    def server_bind(self):
        # "::" listens on IPv6 *and* IPv4 (dual stack), so a platform proxy reaches the
        # server whichever protocol it uses (Railway's edge; deployment plan B2).
        if self.address_family == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except OSError:
                pass
        super().server_bind()

    def track(self, delta: int) -> None:
        with self._active_lock:
            self._active += delta

    def wait_idle(self, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while True:
            with self._active_lock:
                if self._active <= 0:
                    return True
            if time.monotonic() >= end:
                return False
            time.sleep(0.05)


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
        self.server.track(+1)
        self._new_token = None
        self._https = self.server.trust_proxy and \
            (self.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"
        try:
            self._check_host()
            self.owner = self._owner()
            ok, wait = self.server.all_limiter.take(self._client_ip())
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
            self.server.track(-1)
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
                                    "max_chars": config.MAX_TEXT_CHARS,
                                    "suggest": suggest.suggestion_index(self.server.retriever),
                                    "terms": glossary(self.server.retriever),
                                    "retention_days": config.SETTINGS.retention_days,
                                    "help_links": [{"label": l, "url": u} for l, u in config.HELP_LINKS]})
        if path == "/api/schemes":
            self._allow(method, "GET")
            return self._json(200, scheme_list(self.server.retriever))
        if path.startswith("/api/schemes/"):
            self._allow(method, "GET")
            card = scheme_card(self.server.retriever, path[len("/api/schemes/"):])
            if card is None:
                raise ApiError(404, "Unknown scheme")
            return self._json(200, card)
        if path == "/api/threads":
            self._allow(method, "GET", "POST", "DELETE")
            if method == "DELETE":                          # "Clear all chats": this browser's only
                self._check_write()
                self.server.store.delete_all(owner=self.owner)
                return self._empty(204)
            if method == "GET":
                if not self.server.public:              # chats saved before B1 stay visible locally
                    self.server.store.claim_unowned(self.owner)
                return self._json(200, self.server.store.list_threads(owner=self.owner))
            self._check_write()
            self._read_json(required=False)
            t = self.server.store.create_thread(owner=self.owner)
            return self._json(201, {"id": t["id"], "title": t["title"]})
        if path.startswith(_THREAD_PATH):
            rest = path[len(_THREAD_PATH):]
            if rest.endswith("/feedback") and "/messages/" in rest:
                tid_raw, mid_raw = rest[: -len("/feedback")].split("/messages/", 1)
                tid = self._thread_id(tid_raw)
                self._allow(method, "POST")
                return self._feedback(tid, mid_raw)
            if rest.endswith("/messages"):
                tid = self._thread_id(rest[: -len("/messages")])
                self._allow(method, "GET", "POST")
                if method == "GET":
                    return self._json(200, self.server.store.get_messages(tid, owner=self.owner))
                return self._post_message(tid)
            tid = self._thread_id(rest)
            self._allow(method, "DELETE", "PATCH")
            self._check_write()
            if method == "PATCH":
                return self._patch_thread(tid)
            if not self.server.store.delete_thread(tid, owner=self.owner):
                raise ThreadNotFound(tid)
            return self._empty(204)
        raise ApiError(404, "Not found")

    # --- endpoints ------------------------------------------------------------
    def _patch_thread(self, tid: str) -> int:
        body = self._read_json(required=True)
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object")
        title, pinned = body.get("title"), body.get("pinned")
        if title is not None and (not isinstance(title, str) or not title.strip() or len(title) > 200):
            raise ApiError(400, "Title must be 1-60 characters")
        if pinned is not None and not isinstance(pinned, bool):
            raise ApiError(400, "pinned must be true or false")
        return self._json(200, self.server.store.update_thread(tid, title=title, pinned=pinned, owner=self.owner))

    def _feedback(self, tid: str, mid_raw: str) -> int:
        self._check_write()
        if not mid_raw.isdigit() or len(mid_raw) > 12:
            raise ApiError(400, "Invalid message id")
        body = self._read_json(required=True)
        value = body.get("value") if isinstance(body, dict) else None
        if isinstance(value, bool) or value not in (1, -1, 0):
            raise ApiError(400, "value must be 1, -1 or 0")
        reason = body.get("reason")
        if reason is not None and reason not in FEEDBACK_REASONS:
            raise ApiError(400, f"reason must be one of {', '.join(FEEDBACK_REASONS)}")
        if not self.server.store.set_feedback(tid, int(mid_raw), value, reason=reason, owner=self.owner):
            raise ApiError(404, "Message not found")
        return self._empty(204)

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
        ok, wait = self.server.msg_limiter.take(self._client_ip())
        if not ok:
            raise ApiError(429, "Too many messages. Please wait a moment.", {"Retry-After": str(wait)})
        ctx = self.server.store.get_ctx(tid, owner=self.owner)   # 404 if gone or another browser's
        reply, new_ctx = pipeline.handle(text, ctx, retriever=self.server.retriever, rephrase=self.server.rephrase)
        try:
            message_id = self.server.store.add_exchange(tid, guards.redact(text), reply, new_ctx.get("last_scheme"),
                                           owner=self.owner)
        except ThreadNotFound:
            raise
        except Exception as e:                             # THR-06: never show an unsaved reply as saved
            log.error("could not save message: %s", type(e).__name__)
            raise ApiError(500, "Could not save message") from None
        return self._json(200, {**reply.to_dict(), "id": message_id})

    def _health(self) -> dict:
        r = self.server.retriever
        return {"status": "ok", "version": VERSION, "llm_enabled": self.server.rephrase is not None, "retriever": r.backend_name(),
                "corpus_built_on": r.meta.get("built_on"), "data_age_days": data_age_days(r.meta.get("built_on")),
                "schemes": len(r.meta.get("schemes", {}))}

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
        if host in self.server.allowed_hosts:
            return
        if self.server.public and host == HEALTHCHECK_HOST and self.command == "GET" \
                and urlsplit(self.path).path == "/api/health":
            return                                      # Railway's deploy-time healthcheck only
        raise ApiError(403, "Forbidden host")

    def _client_ip(self) -> str:
        """The visitor's IP: X-Real-IP from Railway's edge when trusted (B4), else the socket's."""
        if self.server.trust_proxy:
            real = (self.headers.get("X-Real-IP") or "").strip()
            if real and len(real) <= 64:
                return real
        return self.client_address[0]

    def _owner(self) -> str:
        """SHA-256 of this browser's owner token; issues a new token if there is none (B1)."""
        token = None
        raw = self.headers.get("Cookie")
        if raw:
            try:
                morsel = SimpleCookie(raw).get(OWNER_COOKIE)
            except CookieError:
                morsel = None
            if morsel is not None and _TOKEN.match(morsel.value):
                token = morsel.value
        if token is None:
            token = self._new_token = secrets.token_urlsafe(32)
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _session_headers(self):
        if getattr(self, "_new_token", None):
            flags = "; Secure" if self._https else ""
            self.send_header("Set-Cookie", f"{OWNER_COOKIE}={self._new_token}; Path=/; "
                                           f"Max-Age={OWNER_COOKIE_MAX_AGE}; HttpOnly; SameSite=Strict{flags}")
        if getattr(self, "_https", False):
            self.send_header("Strict-Transport-Security", "max-age=31536000")     # B6

    def _check_write(self):
        origin = self.headers.get("Origin")
        if origin is not None and origin.strip().lower() not in self.server.allowed_origins:
            raise ApiError(403, "Forbidden origin")
        if self.command in ("POST", "PATCH"):
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
        self._session_headers()

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
        self._session_headers()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return status


STALE_AFTER_DAYS = 3

# --- Read-only scheme data for the scheme browser and fact cards ----------------
GROUP_ORDER = ("Equity", "Hybrid", "Debt", "FoF")
_TOPIC_ORDER = list(TOPIC_LABELS)
# Official definitions shown when a term in an answer is tapped: official note topic -> words.
GLOSSARY = {
    "expense_ratio_general": ("expense ratio", "TER"),
    "exit_load_general": ("exit load",),
    "riskometer_general": ("riskometer",),
    "plans_general": ("Direct Plan", "Regular Plan"),
    "sip_general": ("SIP",),
    "lock_in_general": ("ELSS", "lock-in"),
}


def scheme_list(r) -> list[dict]:
    """The 27 schemes, grouped (Equity, Hybrid, Debt, FoF) in registry order."""
    meta = r.meta.get("schemes", {})
    out = []
    for s in registry.SCHEMES:
        m = meta.get(s.id)
        if m:
            out.append({"id": s.id, "name": m["name"], "group": m.get("group"), "category": m.get("category")})
    out.sort(key=lambda x: GROUP_ORDER.index(x["group"]) if x["group"] in GROUP_ORDER else len(GROUP_ORDER))
    return out


def scheme_card(r, scheme_id: str) -> dict | None:
    """Every stored fact of one scheme, each with its own source and date (facts only)."""
    m = r.meta.get("schemes", {}).get(scheme_id)
    if m is None:
        return None
    facts = [c for c in r.chunks if c.get("scheme_id") == scheme_id]
    facts.sort(key=lambda c: _TOPIC_ORDER.index(c["topic"]) if c["topic"] in _TOPIC_ORDER else 99)
    return {"id": scheme_id, "name": m["name"], "label": m.get("label"), "group": m.get("group"),
            "category": m.get("category"), "url": m.get("url"),
            "facts": [{"topic": c["topic"], "label": TOPIC_LABELS.get(c["topic"], c["topic"]), "text": c["text"],
                       "source": {"url": c["source_url"], "name": c["source_name"]}, "as_of": c["as_of"]}
                      for c in facts]}


def glossary(r) -> list[dict]:
    """Official definitions for terms that appear in answers (shown when a term is tapped)."""
    out = []
    for topic, words in GLOSSARY.items():
        c = next((c for c in r.chunks if not c.get("scheme_id") and c["topic"] == topic), None)
        if c:
            out.append({"words": list(words), "text": c["text"],
                        "source": {"url": c["source_url"], "name": c["source_name"]}, "as_of": c["as_of"]})
    return out


def data_age_days(built_on: str | None, today: dt.date | None = None) -> int | None:
    """Days since the corpus was built ("22 Nov 2026"), or None if unknown (Phase 7)."""
    try:
        built = dt.datetime.strptime(built_on or "", "%d %b %Y").date()
    except ValueError:
        return None
    return ((today or dt.date.today()) - built).days


def make_server(host: str | None = None, port: int | None = None, *, store: Store | None = None,
                retriever: Retriever | None = None, rate_msg: int | None = None,
                rate_all: int | None = None, public_hosts: tuple[str, ...] | None = None,
                trust_proxy: bool | None = None, rephrase=None) -> BoloSIPServer:
    """Build (not start) a server. Port 0 picks a free port (tests)."""
    s = config.SETTINGS
    host = s.host if host is None else host
    return BoloSIPServer(
        (host, s.port if port is None else port),
        store=store or Store(s.db_path), retriever=retriever or get_retriever(),
        rate_msg=rate_msg or s.rate_msg_per_min, rate_all=rate_all or s.rate_all_per_min,
        extra_hosts=(host.lower(),),
        public_hosts=s.public_hosts if public_hosts is None else public_hosts,
        trust_proxy=s.trust_proxy if trust_proxy is None else trust_proxy, rephrase=rephrase)


def purge_old_chats(store: Store, days: int) -> None:
    if days > 0:
        n = store.purge_older_than(days)
        if n:
            log.info("Deleted %d chat(s) not used for %d days (BOLOSIP_RETENTION_DAYS).", n, days)


def _start_retention_sweeps(store: Store, days: int, stop: threading.Event) -> None:
    def loop():
        while not stop.wait(RETENTION_SWEEP_S):
            try:
                purge_old_chats(store, days)
            except Exception as e:                     # never take the server down
                log.error("chat retention sweep failed: %s", type(e).__name__)
    if days > 0:
        threading.Thread(target=loop, name="retention", daemon=True).start()


def _install_sigterm(httpd: BoloSIPServer, stopped: threading.Event, *others: BoloSIPServer) -> None:
    """On SIGTERM (every Railway redeploy): stop accepting, let requests in flight finish (B5)."""
    def on_term(signum, frame):
        if stopped.is_set():
            return
        stopped.set()
        log.info("SIGTERM: finishing requests in flight, then stopping.")
        for srv in (httpd, *others):
            threading.Thread(target=srv.shutdown, name="shutdown", daemon=True).start()
    try:
        signal.signal(signal.SIGTERM, on_term)
    except (ValueError, OSError):                       # not the main thread, or unsupported
        pass


_LOOPBACK = ("127.0.0.1", "localhost", "::1")


def hosting_checks(s, environ) -> str:
    """The host to bind, plus warnings for settings that break a Railway deploy (ISS-052).

    Railway sets RAILWAY_* variables in every container. There, a loopback host (often
    copied from a laptop .env) would make the site unreachable ("Application failed to
    respond"), so it is replaced by "::"; the other risky settings are only logged."""
    on_railway = any(k.startswith("RAILWAY_") for k in environ)
    if not on_railway:
        return s.host
    host = s.host
    if host in _LOOPBACK:
        log.warning("BOLOSIP_HOST=%s cannot be reached from outside the container on Railway; listening "
                    "on :: instead. Remove BOLOSIP_HOST from the Railway variables.", host)
        host = "::"
    if not s.public_hosts:
        log.warning("No public host name: set BOLOSIP_PUBLIC_HOSTS (or generate a Railway domain), "
                    "otherwise every public request gets 403 Forbidden host.")
    if not s.trust_proxy:
        log.warning("BOLOSIP_TRUST_PROXY is off on Railway: all visitors share one rate limit. Set it to 1.")
    mount = environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if not mount:
        log.warning("No Railway volume: chats are lost on every redeploy. Attach a volume at /data.")
    elif not str(s.db_path).replace("\\", "/").startswith(mount.rstrip("/") + "/"):
        log.warning("BOLOSIP_DB (%s) is not on the volume (%s): chats are lost on every redeploy.",
                    s.db_path, mount)
    return host


def main(argv: list[str] | None = None) -> int:
    from bolosip.textutil import utf8_output
    utf8_output()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = config.SETTINGS
    host = hosting_checks(s, os.environ)              # ISS-052: never bind loopback on Railway
    if host not in ("127.0.0.1", "localhost", "::1"):
        if s.trust_proxy and s.public_hosts:            # B8: public on purpose, behind an HTTPS edge
            log.info("Public site for %s behind a proxy: no sign-in by design; each browser sees only "
                     "its own chats, rate limits are per visitor (SEC-03).", ", ".join(s.public_hosts))
        else:
            log.warning("Listening on %s: BoloSIP has no authentication, so anyone who can reach this "
                        "address can use it (SEC-03).", host)
    retriever = get_retriever()                       # load the corpus and the model once, before serving
    rephrase = llm.get_rephraser()                    # Phase 8; None = extractive answers
    if rephrase is None and s.llm_mode == "on":
        log.error("BOLOSIP_LLM=on but the LLM is unavailable: %s.", llm.unavailable_reason())
        return 2
    httpd = make_server(host, retriever=retriever, rephrase=rephrase)
    # ISS-048: also listen on BOLOSIP_ALSO_PORT (8000 in the container), so the site works
    # whether the platform's domain points at its own PORT or at 8000.
    extra = None
    if s.also_port and s.also_port != httpd.server_address[1]:
        extra = make_server(host, port=s.also_port, store=httpd.store, retriever=retriever, rephrase=rephrase)
        threading.Thread(target=extra.serve_forever, name=f"port-{s.also_port}", daemon=True).start()
    stopped = threading.Event()
    purge_old_chats(httpd.store, s.retention_days)
    _start_retention_sweeps(httpd.store, s.retention_days, stopped)
    _install_sigterm(httpd, stopped, *([extra] if extra else []))
    shown = f"[{host}]" if ":" in host else host
    ports = f"{httpd.server_address[1]}" + (f" and {extra.server_address[1]}" if extra else "")
    log.info("BoloSIP %s on http://%s port %s (retriever: %s). %s", VERSION, shown, ports,
             retriever.backend_name(), config.DISCLAIMER)
    age = data_age_days(retriever.meta.get("built_on"))
    if age is not None and age > STALE_AFTER_DAYS:
        log.warning("The data is %d days old (built %s). The daily refresh may have stopped: run "
                    "`git pull` and restart, or check the refresh-data workflow on GitHub.",
                    age, retriever.meta.get("built_on"))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        if not httpd.wait_idle(SHUTDOWN_GRACE_S):
            log.warning("Stopped with requests still in flight after %d s.", SHUTDOWN_GRACE_S)
        httpd.server_close()
        if extra:
            extra.shutdown()
            extra.server_close()
        log.info("BoloSIP stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
