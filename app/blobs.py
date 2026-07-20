# app/blobs.py
"""Object storage for render outputs behind a tiny interface.

Final renders are large PNGs; v1 wrote them next to the region. LocalBlobs keeps
that (filesystem), but routing outputs through a put/path/exists/delete interface
means a networked object store (S3/GCS) drops in later without touching the render
or job code -- the worker just gets a different Blobs implementation.

TTL/eviction (red-team V1-8): a back-to-back concierge day otherwise leaks disk, since
finals were never cleaned up. `ttl_seconds` bounds how long a blob lives; put() sweeps
opportunistically so no background thread is needed for a single-operator local tool."""
from __future__ import annotations
import logging
import os
import time

log = logging.getLogger("tecopa.blobs")

class LocalBlobs:
    def __init__(self, root: str = "blobs", ttl_seconds: float | None = None):
        self.root = root
        self.ttl_seconds = ttl_seconds
        os.makedirs(root, exist_ok=True)

    def _p(self, key: str) -> str:
        # keys may be nested ("sessionid/final.png"); keep them under root. Compare
        # path components, not string prefixes: startswith let "../blobs-evil/x"
        # escape a root named "blobs" (red-team).
        path = os.path.normpath(os.path.join(self.root, key))
        root = os.path.normpath(self.root)
        if os.path.commonpath([root, path]) != root:
            raise ValueError("blob key escapes store root")
        return path

    def put(self, key: str, data: bytes) -> str:
        self.sweep()                         # opportunistic eviction on every write
        path = self._p(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def path(self, key: str) -> str:
        return self._p(key)

    def exists(self, key: str) -> bool:
        return os.path.exists(self._p(key))

    def delete(self, key: str) -> None:
        try:
            os.remove(self._p(key))
        except FileNotFoundError:
            pass

    def sweep(self) -> int:
        """Delete blobs older than ttl_seconds (by mtime) and prune emptied dirs.
        No-op when ttl_seconds is falsy. Returns the count removed."""
        if not self.ttl_seconds:
            return 0
        cutoff = time.time() - self.ttl_seconds
        removed = 0
        for dirpath, _dirs, files in os.walk(self.root, topdown=False):
            for fn in files:
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getmtime(p) < cutoff:
                        os.remove(p)
                        removed += 1
                except OSError:
                    pass
            if dirpath != self.root:         # prune a session dir once empty
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass                     # not empty -> leave it
        if removed:
            log.info("event=blobs.sweep removed=%d ttl_s=%s", removed, self.ttl_seconds)
        return removed
