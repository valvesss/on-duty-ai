"""Local on-duty store: ~/.on-duty/on-duty.db (SQLite, kept outside the repo so it survives updates).

events  — one row per spoken line (kind=alert) or per return to the keyboard (kind=back)
profile — key/value JSON: posture calibration, etc.

Schema changes go in MIGRATIONS (append only); PRAGMA user_version tracks how many have run.
"""

import json
import pathlib
import sqlite3
import threading
import time

DB_PATH = pathlib.Path.home() / ".on-duty" / "on-duty.db"
HISTORY_DAYS = 90  # what /history (the dashboard) reads; older rows stay in the file until retention prunes them
_lock = threading.Lock()
_con: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id      INTEGER PRIMARY KEY,
  t       INTEGER NOT NULL,          -- epoch of the event
  kind    TEXT NOT NULL,             -- alert | back
  start   INTEGER,                   -- back: when the phone session started
  minutes REAL,                      -- back: minutes on the phone
  n       INTEGER,                   -- alert: line number within the session | back: total lines spoken
  level   INTEGER,                   -- alert: nag level 1..5
  cause   TEXT,                      -- alert: face | phone | face+phone
  said    TEXT                       -- what the voice said
);
CREATE INDEX IF NOT EXISTS events_t ON events(t);
CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated INTEGER NOT NULL);
"""

MIGRATIONS = [
    # 1: protocol values are English (early builds wrote Portuguese causes, or none for imported rows)
    """
    UPDATE events SET cause = 'face+phone' WHERE cause = 'rosto+celular';
    UPDATE events SET cause = 'face'  WHERE cause = 'rosto';
    UPDATE events SET cause = 'phone' WHERE cause = 'celular';
    UPDATE events SET cause = 'face'  WHERE kind = 'alert' AND cause IS NULL;
    """,
    # 2: the dashboard's "time on phone today" and streaks read back rows by start time
    "CREATE INDEX IF NOT EXISTS events_kind_start ON events(kind, start);",
]


def con() -> sqlite3.Connection:
    global _con
    if _con is None:
        DB_PATH.parent.mkdir(exist_ok=True)
        _con = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        _con.execute("PRAGMA journal_mode=WAL")
        _con.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; far fewer fsyncs
        _con.executescript(SCHEMA)
        version = _con.execute("PRAGMA user_version").fetchone()[0]
        for i in range(version, len(MIGRATIONS)):
            _con.executescript(f"BEGIN; {MIGRATIONS[i]} PRAGMA user_version = {i + 1}; COMMIT;")
    return _con


def record(kind: str, **kw) -> None:
    cols = ["t", "kind", *kw]
    with _lock:
        con().execute(f"INSERT INTO events ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [int(time.time()), kind, *kw.values()])


def prune(retention_days: int) -> int:
    """Delete events older than retention_days (0 = keep forever). Returns rows removed."""
    if retention_days <= 0:
        return 0
    with _lock:
        cur = con().execute("DELETE FROM events WHERE t < ?", (int(time.time()) - retention_days * 86400,))
    return cur.rowcount


def history_ndjson() -> bytes:
    """The last HISTORY_DAYS of events, one JSON object per line (back rows expose n as `alerts`)."""
    with _lock:
        rows = con().execute("SELECT t, kind, start, minutes, n, level, cause, said FROM events WHERE t >= ? ORDER BY t",
                             (int(time.time()) - HISTORY_DAYS * 86400,)).fetchall()
    out = []
    for t, kind, start, minutes, n, level, cause, said in rows:
        e = {"t": t, "kind": kind, "start": start, "minutes": minutes, "level": level, "cause": cause, "said": said}
        e["alerts" if kind == "back" else "n"] = n
        out.append(json.dumps({k: v for k, v in e.items() if v is not None}))
    return "\n".join(out).encode()


def get(key: str, default=None):
    with _lock:
        row = con().execute("SELECT value, updated FROM profile WHERE key=?", (key,)).fetchone()
    return (json.loads(row[0]), row[1]) if row else (default, 0)


def put(key: str, value) -> None:
    with _lock:
        con().execute("INSERT INTO profile VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                      "updated=excluded.updated", (key, json.dumps(value), int(time.time())))


def keys(prefix: str) -> list[str]:
    with _lock:
        return [r[0] for r in con().execute("SELECT key FROM profile WHERE key LIKE ? ESCAPE '\\'", (prefix.replace("%", "\\%") + "%",))]


def delete(key: str) -> None:
    with _lock:
        con().execute("DELETE FROM profile WHERE key=?", (key,))
