# app/session.py
import uuid
_SESSIONS = {}   # single user, single machine (invariant: no DB in v1)

def create(data: dict) -> str:
    sid = uuid.uuid4().hex
    _SESSIONS[sid] = data
    return sid

def get(sid: str) -> dict:
    return _SESSIONS[sid]

def update(sid: str, **kw):
    _SESSIONS[sid].update(kw)
