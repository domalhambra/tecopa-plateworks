# app/store.py
"""Session persistence behind a tiny interface.

v1 kept sessions in a process-local dict (lost on every restart). This is the one
file the handoff flagged as "the only file that becomes a DB": MemoryStore keeps
the old behavior, SqliteStore persists serialized sessions so work survives a
restart, and the interface leaves a clean seam for a networked store (Postgres)
later. Default stays in-memory, so nothing changes unless TRAILPRINT_STORE asks.

Stores return a *copy* of the session on get(); callers mutate it and write back
via update() (the read-modify-write pattern main.py already uses), so the same
code path works whether state lives in RAM or on disk."""
from __future__ import annotations
import copy, json, os, sqlite3, threading, uuid
from app import serialize

class MemoryStore:
    def __init__(self):
        self._d: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, data: dict) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._d[sid] = copy.copy(data)
        return sid

    def has(self, sid: str) -> bool:
        return sid in self._d

    def get(self, sid: str) -> dict:
        return copy.copy(self._d[sid])           # KeyError -> caller maps to 404

    def update(self, sid: str, **kw):
        with self._lock:
            self._d[sid].update(kw)

class SqliteStore:
    """Persists each session as one JSON row. Serialization (tracks/spec) is shared
    with the render queue via serialize.py."""
    def __init__(self, path: str = "trailprint.db"):
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, data TEXT)")

    def _conn(self):
        return sqlite3.connect(self.path)

    def _write(self, sid: str, data: dict):
        blob = json.dumps(serialize.dump_session(data))
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO sessions (id, data) VALUES (?, ?)", (sid, blob))

    def _read(self, sid: str) -> dict:
        with self._conn() as c:
            row = c.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()
        if row is None:
            raise KeyError(sid)
        return serialize.load_session(json.loads(row[0]))

    def create(self, data: dict) -> str:
        sid = uuid.uuid4().hex
        self._write(sid, data)
        return sid

    def has(self, sid: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone() is not None

    def get(self, sid: str) -> dict:
        return self._read(sid)

    def update(self, sid: str, **kw):
        data = self._read(sid)                   # read-modify-write
        data.update(kw)
        self._write(sid, data)

def make_store(kind: str = "memory", **kw):
    kind = (kind or "memory").lower()
    if kind == "sqlite":
        return SqliteStore(kw.get("path", os.environ.get("TRAILPRINT_DB", "trailprint.db")))
    return MemoryStore()
