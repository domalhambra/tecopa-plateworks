# app/basecache.py
"""A byte-budgeted LRU for the painted terrain base.

The studio is a live design tool: every knob in the appearance sidebar stales the
proof, and a proof is a full render from the DEM up. But ~90% of that render is
`render._paint_base` -- the terrain layer -- and most knobs cannot change it. Measured
on an 18x24 sheet: the base is 7.99s of an 8.80s draft (96 dpi) and 25.9s of the ~200
dpi refine, while the route and the sheet furniture together are under 10%.

This module is only the STORE. What may be reused, and when, is `render.base_cache_key`
-- deliberately kept next to the painter whose inputs it describes.

Bounded by BYTES, not entry count: an entry swings ~20x between a 96 dpi draft (~12 MB)
and a 200 dpi refine of a High-relief sheet (~280 MB, because the plan-oblique context
carries a padded elevation and winner buffer).

Process-local on purpose, the same posture as jobs.ThreadJobQueue. A shared or
cross-process cache would first have to upgrade render._plate_fingerprint from an mtime
to a real content hash.
"""
from __future__ import annotations
import logging
import threading
from collections import OrderedDict

log = logging.getLogger("tecopa.basecache")

DEFAULT_MB = 256


class BaseCache:
    """An LRU on a byte budget. Thread-safe: the synchronous /api/proof request thread
    and the PROOF_QUEUE refine worker both reach it."""

    def __init__(self, max_bytes: int = DEFAULT_MB * 1_000_000):
        self.max_bytes = max(0, int(max_bytes))
        self._entries: OrderedDict = OrderedDict()
        self._sizes: dict = {}
        self._bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        """A 0 budget disables the cache completely -- the escape hatch for a
        memory-tight host or an archival run (TECOPA_BASE_CACHE_MB=0)."""
        return self.max_bytes > 0

    def get(self, key: str):
        if not self.enabled:
            return None
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)          # most recently used goes last
            self.hits += 1
            return entry

    def put(self, key: str, entry, nbytes: int) -> None:
        # An entry bigger than the whole budget is not admitted at all: taking it would
        # evict everything else and then be evicted itself on the very next put.
        if not self.enabled or nbytes > self.max_bytes:
            return
        with self._lock:
            if key in self._entries:
                self._bytes -= self._sizes.pop(key)
                del self._entries[key]
            self._entries[key] = entry
            self._sizes[key] = nbytes
            self._bytes += nbytes
            while self._bytes > self.max_bytes:     # the new entry fits, so this stops
                old, _ = self._entries.popitem(last=False)
                self._bytes -= self._sizes.pop(old)
                log.debug("event=basecache.evict bytes=%d", self._bytes)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._sizes.clear()
            self._bytes = 0

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._entries), "bytes": self._bytes,
                    "max_bytes": self.max_bytes, "hits": self.hits,
                    "misses": self.misses}
