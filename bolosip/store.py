"""Thread store: SQLite, one connection per call (architecture §5.3, §12).

* WAL mode, foreign keys on, 5 s busy timeout (THR-04).
* A user message and its reply are written in **one transaction**, after checking the
  thread still exists, so a delete during a request never leaves an orphan (THR-02).
* User text is redacted by the caller **and again here** (`guards.redact` is
  idempotent), so no code path can store personal data unredacted (AC 6).
* The schema is (re)created on every connection with IF NOT EXISTS, so a deleted
  database file is simply recreated on the next request (THR-05).
* Only parameterised queries (SEC-02).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from bolosip import config, guards
from bolosip.formatter import Reply

NEW_TITLE = "New chat"                 # THR-09
MAX_THREADS_LISTED = 100               # THR-07
MAX_MESSAGES_RETURNED = 200            # THR-08: the latest 200 messages of a thread

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  last_scheme TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id   TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('user','assistant')),
  text        TEXT NOT NULL,
  kind        TEXT,
  source_url  TEXT,
  source_name TEXT,
  as_of       TEXT,
  candidates  TEXT,
  scheme_id   TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_threads_updated ON threads(updated_at);
"""


class ThreadNotFound(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def title_from(text: str) -> str:
    """First question, redacted, at most 60 characters (arch §5.3)."""
    t = " ".join(guards.redact(text).split())
    limit = config.THREAD_TITLE_CHARS
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or config.SETTINGS.db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect():
            pass

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)   # autocommit; explicit BEGIN
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA journal_mode = WAL")
            # WAL + NORMAL: no corruption on a crash; at worst the last exchange is lost on a
            # power cut. Avoids an fsync on every message (slow and spiky on Windows).
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(SCHEMA)
            yield conn
        finally:
            conn.close()

    # --- threads -------------------------------------------------------------
    def create_thread(self) -> dict:
        tid, now = str(uuid.uuid4()), _now()
        with self._connect() as c:
            c.execute("INSERT INTO threads (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                      (tid, NEW_TITLE, now, now))
        return {"id": tid, "title": NEW_TITLE, "created_at": now, "updated_at": now}

    def list_threads(self, limit: int = MAX_THREADS_LISTED) -> list[dict]:
        with self._connect() as c:
            rows = c.execute("SELECT id, title, updated_at FROM threads ORDER BY updated_at DESC, rowid DESC "
                             "LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_thread(self, thread_id: str) -> dict | None:
        with self._connect() as c:
            row = c.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        return dict(row) if row else None

    def get_ctx(self, thread_id: str) -> dict:
        t = self.get_thread(thread_id)
        if t is None:
            raise ThreadNotFound(thread_id)
        return {"last_scheme": t["last_scheme"]} if t["last_scheme"] else {}

    def delete_thread(self, thread_id: str) -> bool:
        with self._connect() as c:
            cur = c.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        return cur.rowcount > 0

    # --- messages ------------------------------------------------------------
    def get_messages(self, thread_id: str, limit: int = MAX_MESSAGES_RETURNED) -> list[dict]:
        if self.get_thread(thread_id) is None:
            raise ThreadNotFound(thread_id)
        with self._connect() as c:
            rows = c.execute("SELECT * FROM (SELECT * FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT ?) "
                             "ORDER BY id", (thread_id, limit)).fetchall()
        out = []
        for r in rows:
            out.append({
                "role": r["role"], "text": r["text"], "kind": r["kind"],
                "source": {"url": r["source_url"], "name": r["source_name"]} if r["source_url"] else None,
                "footer": f"Last updated from sources: {r['as_of']}" if r["as_of"] else None,
                "candidates": json.loads(r["candidates"]) if r["candidates"] else None,
                "scheme_id": r["scheme_id"], "created_at": r["created_at"],
            })
        return out

    def add_exchange(self, thread_id: str, user_text: str, reply: Reply, last_scheme: str | None) -> None:
        """Store the (redacted) question and its reply, and the thread's new context, atomically."""
        safe = guards.redact(user_text)                       # second line of defence (AC 6)
        as_of = reply.footer.split(": ", 1)[1] if reply.footer else None
        now = _now()
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                t = c.execute("SELECT title FROM threads WHERE id = ?", (thread_id,)).fetchone()
                if t is None:
                    raise ThreadNotFound(thread_id)
                c.execute("INSERT INTO messages (thread_id, role, text, created_at) VALUES (?, 'user', ?, ?)",
                          (thread_id, safe, now))
                c.execute("INSERT INTO messages (thread_id, role, text, kind, source_url, source_name, as_of, "
                          "candidates, scheme_id, created_at) VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?)",
                          (thread_id, reply.text, reply.kind,
                           reply.source.url if reply.source else None,
                           reply.source.name if reply.source else None, as_of,
                           json.dumps(list(reply.candidates)) if reply.candidates else None,
                           reply.scheme_id, now))
                title = title_from(safe) if t["title"] == NEW_TITLE else t["title"]
                c.execute("UPDATE threads SET title = ?, updated_at = ?, last_scheme = ? WHERE id = ?",
                          (title, now, last_scheme, thread_id))
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise
