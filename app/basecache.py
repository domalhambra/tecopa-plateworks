# app/basecache.py
"""A byte-budgeted LRU for the painted terrain base.

The studio is a live design tool: every knob in the appearance sidebar stales the
proof, and a proof is a full render from the DEM up. But ~90% of that render is
`render._paint_terrain` -- the terrain layer -- and most knobs cannot change it.
Measured on an 18x24 sheet: caching it takes a knob drag from 6.4s to 0.9s at 96 dpi
and from 26.6s to 5.3s at 200 dpi, so the progressive draft+refine pair a single knob
costs drops from ~33s to ~6s.

This module is only the STORE, and it now backs two layers of the proof loop: the
painted terrain (`render.base_cache_key`) and, above it, the inked route
(`render.ink_cache_key`). What may be reused, and when, lives with each key --
deliberately kept next to the painter whose inputs it describes. The two run as
separate instances with separate budgets because their entries differ by ~50x in size
and nothing is gained by making them compete for one.

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

# The route-ink cache's budget (render.ink_cache_key), which the same store backs.
#
# The quantity that sizes THIS one is the journey count, not the sheet. A weave
# composites one strand per journey and the entry is the sum over strands, so it grows
# with the chronicle -- and a chronicle of a life outdoors is the product's whole
# premise. Measured on the same 18x24 of lassen_ca, weave on:
#
#   journeys   96 dpi draft   200 dpi refine   PAIR     (dense would be)
#          1        0.4 MB           2.2 MB    2.6 MB       255 MB
#          3        1.4 MB           6.7 MB    8.1 MB       765 MB
#         10        4.6 MB          22.4 MB     27 MB      2552 MB
#         25       11.6 MB          56.7 MB     68 MB      6378 MB
#         50       23.2 MB         113.1 MB    136 MB     12757 MB
#
# The dense column is why the layer is stored on its support at all: at 50 journeys the
# packed form is ~1% of it, which is the difference between a cacheable weave and an
# uncacheable one. (After the feather blur a route ribbon is non-zero on ~1% of the
# sheet; see render._ink_pack.)
#
# Every row above is a SYNTHETIC journey -- a straight line across the sheet. A real GPX
# track wanders, so it inks more of the sheet per journey. Re-measured 2026-07-27 on a
# real onX track (105.9 km, 271 verts after simplify) over the real susanville_reno
# plate, same 18x24 at 200 dpi:
#
#   journeys   96 dpi draft   200 dpi refine   PAIR      support
#          1        0.7 MB           3.2 MB    3.8 MB      1.15%
#          3        2.0 MB           9.5 MB   11.5 MB      1.15%
#         10        6.6 MB          31.8 MB   38.3 MB      1.15%
#
# 3.83 MB per journey against the 2.72 MB the synthetic rows imply -- 41% more. So the
# ceiling is nearer **~66 journeys** than the ~90 estimated below, and it scales with
# track LENGTH, not just count: a 106 km day costs more than a 5 km walk. Treat ~66 as
# the number for long tracks and re-measure if the refusals start appearing early.
# (Caveat: the multi-journey rows repeat that one real track at an offset, so the
# geometry is real but the variety is not. A true multi-year set is still unmeasured.)
#
# Sized against the draft+refine PAIR, never the largest single entry -- the lesson from
# the budget above, where admitting the big entry alone scored zero hits out of four on
# a knob drag while looking perfectly healthy. 256 MB covers a 50-journey chronicle's
# pair with room for a second composition. It is ~linear in strands from there, so the
# pair passes the budget somewhere past ~90 SYNTHETIC journeys at 200 dpi (~66 real ones,
# above); that entry is refused rather than thrashed, and the refusal is logged
# (event=basecache.refuse) so it shows up as a diagnosis instead of unexplained
# slowness. TECOPA_INK_CACHE_MB=0 disables it.
INK_DEFAULT_MB = 256


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
        if not self.enabled:
            return
        if nbytes > self.max_bytes:
            # Logged rather than silent: a refusal means every render of this
            # composition pays full price, and the cache looks healthy while buying
            # nothing -- the same failure mode as an undersized budget, which took a
            # measurement to find the first time.
            log.info("event=basecache.refuse bytes=%d max_bytes=%d", nbytes,
                     self.max_bytes)
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
