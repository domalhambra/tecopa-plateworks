# app/session.py
"""The session API the app calls. Now a thin delegate over a pluggable store
(store.py): in-memory by default (v1 behavior), or SQLite-backed persistence when
TECOPA_STORE=sqlite. Same four calls main.py already uses, so the switch is
invisible to the rest of the app."""
import os
from app import store

_STORE = store.make_store(os.environ.get("TECOPA_STORE", "memory"))

def create(data: dict) -> str:
    return _STORE.create(data)

def has(sid: str) -> bool:
    return _STORE.has(sid)

def get(sid: str) -> dict:
    return _STORE.get(sid)        # KeyError on unknown sid -> caller maps to 404

def update(sid: str, **kw):
    _STORE.update(sid, **kw)
