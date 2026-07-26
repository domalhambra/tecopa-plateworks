# app/basecache.py
"""A byte-budgeted LRU for the painted terrain base.

The studio is a live design tool: every knob in the appearance sidebar stales the
proof, and a proof is a full render from the DEM up. But ~90% of that render is
`render._paint_terrain` -- the terrain layer -- and most knobs cannot change it.
Measured on an 18x24 sheet: caching it takes a knob drag from 6.4s to 0.9s at 96 dpi
and from 26.6s to 5.3s at 200 dpi, so the progressive draft+refine pair a single knob
costs drops from ~33s to ~6s.

This module is only the STORE. What may be reused, and when, is `render.base_cache_key`
-- deliberately kept next to the painter whose inputs it describes.

Bounded by BYTES, not entry count: an entry swings ~20x between a 96 dpi draft and a
200 dpi refine of a High-relief sheet, because the plan-oblique context carries a
padded elevation and winner buffer several times the size of the sheet itself.

Process-local on purpose, the same posture as jobs.ThreadJobQueue. A shared or
cross-process cache would first have to upgrade render._plate_fingerprint from an mtime
to a real content hash.
"""
from __future__ import annotations
import logging
import threading
from collections import OrderedDict

log = logging.getLogger("tecopa.basecache")

# Measured on an 18x24 of lassen_ca -- the size this is actually for -- at the two dpis
# the progressive proof renders, which BOTH have to be resident for a knob drag to be
# fast (the sync 96 dpi draft, then the queued 200 dpi refine of the same composition):
#
#              96 dpi draft   200 dpi refine
#   plain          16 MB            69 MB     <-  85 MB for the pair
#   High relief    59 MB           254 MB     <- 312 MB for the pair
#
# The first default was 256 MB, chosen against an estimate of a single ~280 MB entry.
# That was the wrong quantity to size against, and the effect was severe rather than
# marginal: the High-relief refine entry fits on its own, so nothing looked broken, but
# it leaves no room for its own 96 dpi draft. The two tiers then evict each other every
# single step and the drag gets NOTHING. Measured over a three-position drag of one
# route-ink knob: 0 hits out of 4 possible at 256 MB, 4 of 4 at 512 MB -- 101s against
# 47s for the same work.
#
# 512 MB clears the 312 MB pair with room for a second composition's draft, and stays
# modest next to the ~2.2 GB the 200 dpi High-relief render itself peaks at, so it does
# not change the app's memory class. TECOPA_BASE_CACHE_MB=0 still disables it outright.
DEFAULT_MB = 512


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
