# app/jobs.py
"""Render job queue at the compose->rasterize boundary.

The handoff named this seam: compose decides the picture (the stamped
CompositionSpec); rasterize paints it. That spec is the unit of work that crosses
the boundary, so it is exactly the job payload. v1 runs the worker in a daemon
thread (single process) so the UI doesn't block on a 300 dpi render; the same
submit/status interface fronts a real broker + worker pool (Redis/Celery) later
without the API or render code changing."""
from __future__ import annotations
import threading, traceback, uuid

class ThreadJobQueue:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, fn, *args, **kwargs) -> str:
        jid = uuid.uuid4().hex
        with self._lock:
            self._jobs[jid] = {"state": "queued", "result": None, "error": None}

        def run():
            with self._lock:
                self._jobs[jid]["state"] = "running"
            try:
                result = fn(*args, **kwargs)
                with self._lock:
                    self._jobs[jid].update(state="done", result=result)
            except Exception as ex:               # surface failures as job state, not a crash
                with self._lock:
                    self._jobs[jid].update(state="error", error=f"{type(ex).__name__}: {ex}")
                traceback.print_exc()

        threading.Thread(target=run, daemon=True).start()
        return jid

    def status(self, jid: str) -> dict:
        with self._lock:
            if jid not in self._jobs:
                raise KeyError(jid)
            return dict(self._jobs[jid])
