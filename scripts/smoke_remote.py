"""Smoke test for a running BoloSIP site (Doc/deployment-plan.md §4, stage D4).

    python scripts/smoke_remote.py https://<your-app>.up.railway.app
    python scripts/smoke_remote.py http://127.0.0.1:8000 --max-age 30

Standard library only. Acts like two separate browsers (each with its own cookie) and
checks: health (27 schemes, embedding search, data age), the page and its security
headers, one answer with its source and footer, an advice refusal, a personal-data reply,
a foreign-origin write refused, and that browser B cannot see or read browser A's chat.
It creates one chat and deletes it at the end. Exit code 0 when every check passes.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class Browser:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.origin = "{0.scheme}://{0.netloc}".format(urlsplit(self.base))
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body=None, *, origin: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("User-Agent", "bolosip-smoke/1")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if method != "GET":
            req.add_header("Origin", origin or self.origin)
        try:
            with self.opener.open(req, timeout=60) as r:
                status, raw, headers = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, raw, headers = e.code, e.read(), e.headers
        ctype = headers.get("Content-Type") or ""
        parsed = json.loads(raw) if raw and ctype.startswith("application/json") else raw
        return status, parsed, headers


def run(base: str, max_age: int, allow_bm25: bool) -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []

    def check(ok: bool, what: str):
        results.append((bool(ok), what))
        return ok

    https = base.lower().startswith("https://")
    a, b = Browser(base), Browser(base)

    s, h, _ = a.call("GET", "/api/health")
    if not check(s == 200 and isinstance(h, dict) and h.get("status") == "ok", f"health is ok (HTTP {s})"):
        return results
    check(h.get("schemes") == 27, f"27 schemes (got {h.get('schemes')})")
    check(allow_bm25 or str(h.get("retriever", "")).startswith("dense"), f"embedding search ({h.get('retriever')})")
    age = h.get("data_age_days")
    check(age is not None and age <= max_age, f"data is at most {max_age} days old (built {h.get('corpus_built_on')}, "
                                              f"{age} days)")

    s, page, hdr = Browser(base).call("GET", "/")                    # a first visit: gets its cookie
    check(s == 200 and b"BoloSIP" in (page or b""), "chat page loads")
    check("frame-ancestors 'none'" in (hdr.get("Content-Security-Policy") or ""), "Content-Security-Policy sent")
    cookie = hdr.get("Set-Cookie") or ""
    check("HttpOnly" in cookie and "SameSite=Strict" in cookie, "owner cookie is HttpOnly and SameSite=Strict")
    if https:
        check("Secure" in cookie, "owner cookie is Secure")
        check(bool(hdr.get("Strict-Transport-Security")), "Strict-Transport-Security sent")

    s, t, _ = a.call("POST", "/api/threads", {})
    if not check(s == 201 and isinstance(t, dict) and "id" in t, f"new chat created (HTTP {s})"):
        return results
    tid = t["id"]

    def ask(text):
        st, reply, _ = a.call("POST", f"/api/threads/{tid}/messages", {"text": text})
        return st, reply if isinstance(reply, dict) else {}

    st, r = ask("What is the expense ratio of HDFC Mid Cap Fund?")
    check(st == 200 and r.get("kind") == "answer", f"factual question answered ({r.get('kind')})")
    check(str((r.get("source") or {}).get("url", "")).startswith("https://groww.in/"), "answer cites its Groww source")
    check(str(r.get("footer", "")).startswith("Last updated from sources:"), f"answer has its date ({r.get('footer')})")
    st, r = ask("Should I invest in HDFC Mid Cap Fund?")
    check(r.get("kind") == "refusal", f"advice question refused ({r.get('kind')})")
    st, r = ask("My PAN is ABCDE1234F, what is the exit load of HDFC Mid Cap?")
    check(r.get("kind") == "privacy", f"personal data not accepted ({r.get('kind')})")

    st, _, _ = a.call("POST", "/api/threads", {}, origin="https://evil.example")
    check(st == 403, f"write from a foreign site refused (HTTP {st})")

    st, lst, _ = b.call("GET", "/api/threads")
    check(st == 200 and isinstance(lst, list) and all(x.get("id") != tid for x in lst),
          "another browser does not see the chat in its list")
    st, _, _ = b.call("GET", f"/api/threads/{tid}/messages")
    check(st == 404, f"another browser cannot read the chat (HTTP {st})")
    st, _, _ = b.call("DELETE", f"/api/threads/{tid}")
    check(st == 404, f"another browser cannot delete the chat (HTTP {st})")

    st, _, _ = a.call("DELETE", f"/api/threads/{tid}")
    check(st == 204, f"test chat deleted (HTTP {st})")
    return results


def main(argv: list[str] | None = None) -> int:
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bolosip.textutil import utf8_output
    utf8_output()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("url", help="base URL, e.g. https://bolosip.up.railway.app")
    p.add_argument("--max-age", type=int, default=3, help="oldest acceptable data, in days (default 3)")
    p.add_argument("--allow-bm25", action="store_true", help="accept keyword search instead of embeddings")
    args = p.parse_args(argv)
    try:
        results = run(args.url, args.max_age, args.allow_bm25)
    except (urllib.error.URLError, OSError) as e:
        print(f"FAIL  could not reach {args.url}: {e}")
        return 1
    for ok, what in results:
        print(("PASS  " if ok else "FAIL  ") + what)
    failed = sum(not ok for ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
