"""Perfil local do on-duty: ~/.on-duty/on-duty.db (SQLite, fora do repo pra sobreviver a tudo).

events  — 1 linha por fala (kind=alert) ou volta pro teclado (kind=back)
profile — chave/valor JSON: calibração da postura, etc.
"""

import json
import pathlib
import sqlite3
import threading
import time

DB_PATH = pathlib.Path.home() / ".on-duty" / "on-duty.db"
_lock = threading.Lock()
_con: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id      INTEGER PRIMARY KEY,
  t       INTEGER NOT NULL,          -- epoch do evento
  kind    TEXT NOT NULL,             -- alert | back
  start   INTEGER,                   -- back: quando começou a sessão no celular
  minutes REAL,                      -- back: minutos no celular
  n       INTEGER,                   -- alert: nº da fala na sessão | back: total de falas
  level   INTEGER,                   -- alert: nível 1..5
  cause   TEXT,                      -- alert: rosto | celular | rosto+celular
  said    TEXT                       -- o que a voz falou
);
CREATE INDEX IF NOT EXISTS events_t ON events(t);
CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated INTEGER NOT NULL);
"""


def con() -> sqlite3.Connection:
    global _con
    if _con is None:
        DB_PATH.parent.mkdir(exist_ok=True)
        _con = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        _con.execute("PRAGMA journal_mode=WAL")
        _con.executescript(SCHEMA)
    return _con


def record(kind: str, **kw) -> None:
    cols = ["t", "kind", *kw]
    with _lock:
        con().execute(f"INSERT INTO events ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [int(time.time()), kind, *kw.values()])


def history_ndjson() -> bytes:
    """Mesmo formato que o painel já consome (alerts = n na volta)."""
    with _lock:
        rows = con().execute("SELECT t, kind, start, minutes, n, level, cause, said FROM events ORDER BY t").fetchall()
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


def import_jsonl(path: pathlib.Path) -> int:
    """Migra o history.jsonl antigo (uma vez) e renomeia pra .imported."""
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            with _lock:
                con().execute("INSERT INTO events (t, kind, start, minutes, n, level, cause) VALUES (?,?,?,?,?,?,?)",
                              (e["t"], e["kind"], e.get("start"), e.get("minutes"), e.get("alerts", e.get("n")),
                               e.get("level"), e.get("cause")))
            n += 1
    path.rename(path.with_suffix(".jsonl.imported"))
    return n
