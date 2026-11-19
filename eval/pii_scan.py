"""Scan a thread database and logs for personal-data values (AC 6; Phase 5 gate and tests).

Every stored user text (thread titles, user messages) is checked for every value and its
spacing variants, so even a 4-digit fragment ("aadhaar ending 4567") is caught. The raw
database files (including the WAL) and the logs are also scanned byte for byte, but
only for values of 8+ characters: shorter digit runs occur by chance in UUIDs,
timestamps and SQLite's binary pages.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def forms(value: str) -> set[str]:
    return {value, value.replace(" ", ""), value.replace("-", ""), value.lower(), value.upper()}


def stored_text(db: Path) -> str:
    """Everything that came from users: thread titles and user messages. (IDs and
    timestamps are random digits; assistant text comes from the corpus.)"""
    with sqlite3.connect(db) as c:
        parts = [r[0] for r in c.execute("SELECT title FROM threads")]
        parts += [r[0] for r in c.execute("SELECT text FROM messages WHERE role = 'user'")]
    return "\n".join(parts)


def leaked_values(db: Path, values: list[str], logs: str = "") -> list[str]:
    text = stored_text(db)
    raw = b"".join(p.read_bytes() for p in db.parent.iterdir() if p.is_file() and p.name.startswith(db.name))
    found = set()
    for v in values:
        for f in forms(v):
            if f in text or (len(f.replace(" ", "")) >= 8 and (f.encode("utf-8") in raw or f in logs)):
                found.add(v)
    return sorted(found)
