# ingest.py

- _ssl_context · function · L68-L74 — def _ssl_context() -> ssl.SSLContext: # Certificates are still fully verified. Python 3.13+ also enables # VERIFY_X509_STRICT, which rejects some real-world chains (and many corporate / # antivirus TLS proxies), so only that extra strictness flag is relaxed.
- _fetch_urllib · function · L77-L80 — def _fetch_urllib(url: str) -> str
- _fetch_curl · function · L83-L90 — def _fetch_curl(url: str) -> str: # Some sites reject Python's TLS client fingerprint but accept curl.
- fetch · function · L93-L100 — def fetch(url: str) -> str
- parse_scheme · function · L103-L110 — def parse_scheme(html: str) -> dict
- inr · function · L113-L120 — def inr(n) -> str
- iso_to_human · function · L123-L129 — def iso_to_human(s: str | None) -> str | None
- scheme_chunks · function · L132-L197 — def scheme_chunks(sid: str, url: str, d: dict, fetched: str) -> list[dict]
- add · function · L136-L147 — def add(topic: str, text: str)
- main · function · L200-L242 — def main() -> int
