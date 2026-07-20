# app/jobs.py
"""Render job queue at the compose->rasterize boundary.

The handoff named this seam: compose decides the picture (the stamped
CompositionSpec); rasterize paints it. That spec is the unit of work that crosses
the boundary, so it is exactly the job payload. v1 runs the worker in a daemon
thread (single process) so the UI doesn't block on a 300 dpi render; the same
submit/status interface fronts a real broker + worker pool (Redis/Celery) later
without the API or render code changing.

TTL/eviction (red-team V1-8): finished job records were never dropped, so a long
concierge session's registry grew unbounded. `ttl_seconds` bounds how long a
done/error record is kept; submit() evicts expired records opportunistically."""
from __future__ import annotations
import logging
import threading
import time
import uuid

log = logging.getLogger("tecopa.jobs")

class ThreadJobQueue:
    def __init__(self, ttl_seconds: float | None = None, max_concurrency: int = 1):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds
        # Bound concurrent work: every submit used to spawn an unbounded worker
        # thread, so back-to-back finals ran several ~GB 300-dpi renders at once and
        # could OOM the operator's machine (red-team). Excess jobs stay "queued"
        # until a slot frees -- same states, no API change.
        self._slots = threading.Semaphore(max(1, max_concurrency))

    def _evict_expired_locked(self):
        if not self.ttl_seconds:
            return
        cutoff = time.time() - self.ttl_seconds
        stale = [j for j, r in self._jobs.items()
                 if r["state"] in ("done", "error") and (r.get("finished") or 0) < cutoff]
        for j in stale:
            del self._jobs[j]
        if stale:
            log.info("event=jobs.evict removed=%d ttl_s=%s", len(stale), self.ttl_seconds)

    def submit(self, fn, *args, **kwargs) -> str:
        jid = uuid.uuid4().hex
        with self._lock:
            self._evict_expired_locked()
            self._jobs[jid] = {"state": "queued", "result": None, "error": None,
                               "created": time.time(), "finished": None,
                               "progress": None}
        log.info("event=job.submit jid=%s", jid)

        def run():
            with self._slots:              # stay "queued" until a render slot frees
                t0 = time.time()
                with self._lock:
                    self._jobs[jid]["state"] = "running"
                try:
                    result = fn(*args, **kwargs)
                    with self._lock:
                        self._jobs[jid].update(state="done", result=result,
                                               finished=time.time())
                    log.info("event=job.done jid=%s ms=%d", jid,
                             int((time.time() - t0) * 1000))
                except Exception as ex:       # surface failures as job state, not a crash
                    with self._lock:
                        self._jobs[jid].update(state="error",
                                               error=f"{type(ex).__name__}: {ex}",
                                               finished=time.time())
                    # log with traceback to the logger (not vanishing stdout) so a
                    # failed client render is diagnosable (red-team V1-11).
                    log.exception("event=job.error jid=%s", jid)

        threading.Thread(target=run, daemon=True).start()
        return jid

    def set_progress(self, jid: str, text: str) -> None:
        """Worker-updated one-line status for long jobs (region builds). Unknown jid
        is a no-op: the record may have been TTL-evicted mid-build."""
        with self._lock:
            if jid in self._jobs:
                self._jobs[jid]["progress"] = text

    def status(self, jid: str) -> dict:
        with self._lock:
            if jid not in self._jobs:
                raise KeyError(jid)
            return dict(self._jobs[jid])
