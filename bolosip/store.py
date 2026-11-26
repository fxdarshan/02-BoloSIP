"""Thread store: SQLite, one connection per call (architecture §5.3, §12).

* WAL mode, foreign keys on, 5 s busy timeout (THR-04).
* A user message and its reply are written in **one transaction**, after checking the
  thread still exists, so a delete during a request never leaves an orphan (THR-02).
* User text is redacted by the caller **and again here** (`guards.redact` is
  idempotent), so no code path can store personal data unredacted (AC 6).
* The schema is (re)created on every connection with IF NOT EXISTS, so a deleted
  database file is simply recreated on the next request (THR-05).
* Only parameterised queries (SEC-02).
* Each thread belongs to one browser (`owner`, a SHA-256 of the browser's cookie token;
  the token itself is never stored). The server passes `owner=` to every call, and a
  thread of another owner behaves exactly like a missing one (deployment plan B1).
  `owner=None` means unscoped (scripts and tests).
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bolosip import config, guards
from bolosip.formatter import Reply

NEW_TITLE = "New chat"                 # THR-09
MAX_THREADS_LISTED = 100               # THR-07
MAX_MESSAGES_RETURNED = 200            # THR-08: the latest 200 messages of a thread
FEEDBACK_REASONS = ("incorrect", "incomplete", "irrelevant", "other")   # why an answer got a thumbs down

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  last_scheme TEXT,
  owner       TEXT,
  pinned      INTEGER NOT NULL DEFAULT 0
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
  created_at  TEXT NOT NULL,
  feedback    INTEGER,
  feedback_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_threads_updated ON threads(updated_at);
"""
# Created after the migration below, so an old database gets the column first.
OWNER_INDEX = "CREATE INDEX IF NOT EXISTS idx_threads_owner ON threads(owner, updated_at);"


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
        with self._connect() as c:                     # older databases lack the newer columns
            cols = {r["name"] for r in c.execute("PRAGMA table_info(threads)")}
            if "owner" not in cols:
                c.execute("ALTER TABLE threads ADD COLUMN owner TEXT")
            if "pinned" not in cols:
                c.execute("ALTER TABLE threads ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            mcols = {r["name"] for r in c.execute("PRAGMA table_info(messages)")}
            if "feedback" not in mcols:
                c.execute("ALTER TABLE messages ADD COLUMN feedback INTEGER")
            if "feedback_reason" not in mcols:
                c.execute("ALTER TABLE messages ADD COLUMN feedback_reason TEXT")
            c.execute(OWNER_INDEX)

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
    def create_thread(self, *, owner: str | None = None) -> dict:
        tid, now = str(uuid.uuid4()), _now()
        with self._connect() as c:
            c.execute("INSERT INTO threads (id, title, created_at, updated_at, owner) VALUES (?, ?, ?, ?, ?)",
                      (tid, NEW_TITLE, now, now, owner))
        return {"id": tid, "title": NEW_TITLE, "created_at": now, "updated_at": now}

    def list_threads(self, limit: int = MAX_THREADS_LISTED, *, owner: str | None = None) -> list[dict]:
        where, args = ("WHERE owner = ? ", (owner,)) if owner is not None else ("", ())
        with self._connect() as c:
            rows = c.execute(f"SELECT id, title, updated_at, pinned FROM threads {where}"
                             "ORDER BY pinned DESC, updated_at DESC, rowid DESC LIMIT ?", (*args, limit)).fetchall()
        return [{**dict(r), "pinned": bool(r["pinned"])} for r in rows]

    def update_thread(self, thread_id: str, *, title: str | None = None, pinned: bool | None = None,
                      owner: str | None = None) -> dict:
        """Rename (redacted, 1-60 characters) and/or pin a thread. ThreadNotFound if not the owner's."""
        if self.get_thread(thread_id, owner=owner) is None:
            raise ThreadNotFound(thread_id)
        sets, args = [], []
        if title is not None:
            clean = title_from(title)
            if not clean:
                raise ValueError("Title is empty")
            sets.append("title = ?"); args.append(clean)
        if pinned is not None:
            sets.append("pinned = ?"); args.append(1 if pinned else 0)
        if sets:
            with self._connect() as c:
                c.execute(f"UPDATE threads SET {', '.join(sets)} WHERE id = ?", (*args, thread_id))
        t = self.get_thread(thread_id, owner=owner)
        return {"id": t["id"], "title": t["title"], "pinned": bool(t["pinned"])}

    def delete_all(self, *, owner: str) -> int:
        """Delete every thread of one owner (the "Clear all chats" control)."""
        with self._connect() as c:
            return c.execute("DELETE FROM threads WHERE owner = ?", (owner,)).rowcount

    def set_feedback(self, thread_id: str, message_id: int, value: int, *, reason: str | None = None,
                     owner: str | None = None) -> bool:
        """Record +1 / -1 (or 0 to clear) on an assistant message of the owner's thread, with an
        optional reason for a -1 (one of FEEDBACK_REASONS; never free text, so nothing personal)."""
        if self.get_thread(thread_id, owner=owner) is None:
            raise ThreadNotFound(thread_id)
        reason = reason if value == -1 and reason in FEEDBACK_REASONS else None
        with self._connect() as c:
            cur = c.execute("UPDATE messages SET feedback = ?, feedback_reason = ? "
                            "WHERE id = ? AND thread_id = ? AND role = 'assistant'",
                            (value or None, reason, message_id, thread_id))
        return cur.rowcount > 0

    def claim_unowned(self, owner: str) -> int:
        """Give threads saved before B1 (owner NULL) to `owner`. Laptop only: the server
        calls this only when it is not public, so old local chats stay visible."""
        with self._connect() as c:
            return c.execute("UPDATE threads SET owner = ? WHERE owner IS NULL", (owner,)).rowcount

    def get_thread(self, thread_id: str, *, owner: str | None = None) -> dict | None:
        with self._connect() as c:
            row = c.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None or (owner is not None and row["owner"] != owner):
            return None
        return dict(row)

    def get_ctx(self, thread_id: str, *, owner: str | None = None) -> dict:
        t = self.get_thread(thread_id, owner=owner)
        if t is None:
            raise ThreadNotFound(thread_id)
        return {"last_scheme": t["last_scheme"]} if t["last_scheme"] else {}

    def delete_thread(self, thread_id: str, *, owner: str | None = None) -> bool:
        with self._connect() as c:
            if owner is None:
                cur = c.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            else:
                cur = c.execute("DELETE FROM threads WHERE id = ? AND owner = ?", (thread_id, owner))
        return cur.rowcount > 0

    def purge_older_than(self, days: int, *, now: datetime | None = None) -> int:
        """Delete threads not updated for `days` days (B7). Messages go with them (cascade)."""
        if days <= 0:
            return 0
        cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat(timespec="microseconds")
        with self._connect() as c:
            return c.execute("DELETE FROM threads WHERE updated_at < ?", (cutoff,)).rowcount

    # --- messages ------------------------------------------------------------
    def get_messages(self, thread_id: str, limit: int = MAX_MESSAGES_RETURNED, *,
                     owner: str | None = None) -> list[dict]:
        if self.get_thread(thread_id, owner=owner) is None:
            raise ThreadNotFound(thread_id)
        with self._connect() as c:
            rows = c.execute("SELECT * FROM (SELECT * FROM messages WHERE thread_id = ? ORDER BY id DESC LIMIT ?) "
                             "ORDER BY id", (thread_id, limit)).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r["id"], "role": r["role"], "text": r["text"], "kind": r["kind"],
                "feedback": r["feedback"], "feedback_reason": r["feedback_reason"],
                "source": {"url": r["source_url"], "name": r["source_name"]} if r["source_url"] else None,
                "footer": f"Last updated from sources: {r['as_of']}" if r["as_of"] else None,
                "candidates": json.loads(r["candidates"]) if r["candidates"] else None,
                "scheme_id": r["scheme_id"], "created_at": r["created_at"],
            })
        return out

    def add_exchange(self, thread_id: str, user_text: str, reply: Reply, last_scheme: str | None, *,
                     owner: str | None = None) -> int:
        """Store the (redacted) question and its reply, and the thread's new context, atomically.
        Returns the reply's message id (for feedback)."""
        safe = guards.redact(user_text)                       # second line of defence (AC 6)
        as_of = reply.footer.split(": ", 1)[1] if reply.footer else None
        now = _now()
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                t = c.execute("SELECT title, owner FROM threads WHERE id = ?", (thread_id,)).fetchone()
                if t is None or (owner is not None and t["owner"] != owner):
                    raise ThreadNotFound(thread_id)
                c.execute("INSERT INTO messages (thread_id, role, text, created_at) VALUES (?, 'user', ?, ?)",
                          (thread_id, safe, now))
                cur = c.execute(
                          "INSERT INTO messages (thread_id, role, text, kind, source_url, source_name, as_of, "
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
        return cur.lastrowid
