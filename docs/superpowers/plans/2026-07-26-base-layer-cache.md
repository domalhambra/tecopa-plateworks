# Base-layer cache — implementation plan

Goal: stop re-rendering terrain that did not change, so a knob in the appearance sidebar
redraws the proof in ~1.5 s instead of ~26 s.

Architecture: `render._paint_base` (relief + contours + hydro + labels + the oblique
warp) is ~90% of a proof and most knobs cannot change it. Cache its output in a
byte-budgeted process-local LRU, keyed on the spec fields that can actually reach it.
The key is derived by **masking** known-safe fields — never by listing relevant ones —
so a spec field added later lands in the key by default and the worst case is a cache
miss rather than a stale poster. `rasterize` takes `base_cache=None` and that default is
the pre-cache path exactly, so `timelapse`, `mockups`, the wallpaper bundle and the
final path are untouched by construction.

Tech Stack: Python 3.14, numpy, Pillow, rasterio, FastAPI, pytest.

Phasing: **Phase 1 (this plan, Tasks 1–7)** caches the whole `_paint_base` output. It
ships the win for the default poster (place names off) and proves the machinery.
**Phase 2 (Tasks 8–10)** moves the cut point to just before labels are drawn, which
extends the win to every non-terrain knob regardless of label settings.

---

## Measurements this plan is built on

Taken on an 18×24 sheet, `relief_rev=2`, contours on, on a 4-core container. Absolute
seconds are container-slow; the ratios are what transfer.

| | draft 96 dpi | refine 200 dpi |
|---|---|---|
| relief (hillshade, shadows, AO, texture, tonal) | ~6.4 s (80%) | ~21.6 s (84%) |
| contours | 0.28 s (3.6%) | 3.08 s (11.9%) |
| off-DEM probe + DEM read | 0.97 s (12%) | 0.23 s (1%) |
| labels | 0.23 s (2.9%) | 0.56 s (2.2%) |
| route mask (smart labels) | 0.05 s | 0.36 s (1.4%) |
| hydro | 0.01 s | 0.01 s |
| **`_paint_base` total** | **7.99 s (91% of the render)** | **25.87 s** |
| route (`_paint_journey`) | 0.67 s (7.6%) | — |
| overlays (`_paint_overlays`) | 0.14 s (1.6%) | — |

A knob change costs *two* renders: the synchronous 96 dpi draft and the queued ~200 dpi
refine. The refine is ~80% of the felt cost, which is why both tiers are cached.

---

## File map

| File | Responsibility |
|---|---|
| `app/basecache.py` **(new)** | The store only: a thread-safe LRU bounded by bytes. Knows nothing about specs or rendering. |
| `app/render.py` **(modify)** | `_luminance` (extracted), `_plate_fingerprint`, `BASE_KEY_MASK_*`, `base_cache_key`, `_entry_bytes`, `_freeze`, `_base_layer`, and `rasterize(base_cache=...)`. The key lives here because it must be maintained beside the painter whose inputs it describes. |
| `app/main.py` **(modify)** | The `BASE_CACHE` instance and its budget env var; wires it into `/api/proof` and `_render_refine_to_blob` only. |
| `tests/test_base_cache.py` **(new)** | The LRU's behaviour, the key's mask contract (including the field-enumeration guard), and cached-vs-cold pixel equality across the knob matrix. |
| `tests/conftest.py` **(modify)** | Classify the full-render cache tests as `slow`. |
| `CLAUDE.md` **(modify)** | One line in the repo map. |

---

## Task 1: The LRU store

Files:
- Create: `app/basecache.py`
- Test: `tests/test_base_cache.py`

### Step 1: Write the failing test

Create `tests/test_base_cache.py`:

```python
# tests/test_base_cache.py
"""The base-layer cache: the store, the key, and cached-vs-cold pixel equality.

The cache exists because ~90% of every proof is terrain that the knob being dragged
cannot change (see docs/superpowers/plans/2026-07-26-base-layer-cache.md). That makes
it a correctness risk as much as a speed win: a cache that serves a stale base produces
a proof that no longer predicts the print, which is the one bug class this product
cannot have. These tests are the guard, and the field-enumeration test below is the
one that keeps it honest as the spec grows.
"""
import dataclasses
import json
import os

import numpy as np
import pytest

from app import basecache


def test_put_then_get_returns_the_entry():
    c = basecache.BaseCache(1000)
    c.put("k", "payload", 10)
    assert c.get("k") == "payload"
    assert c.stats()["entries"] == 1
    assert c.stats()["bytes"] == 10


def test_missing_key_returns_none_and_counts_a_miss():
    c = basecache.BaseCache(1000)
    assert c.get("nope") is None
    assert c.stats()["misses"] == 1
    assert c.stats()["hits"] == 0


def test_eviction_is_least_recently_used_and_respects_the_budget():
    c = basecache.BaseCache(100)
    c.put("a", "A", 40)
    c.put("b", "B", 40)
    c.get("a")                       # 'a' is now the most recently used
    c.put("c", "C", 40)              # 120 > 100, so the LRU ('b') goes
    assert c.get("b") is None
    assert c.get("a") == "A"
    assert c.get("c") == "C"
    assert c.stats()["bytes"] <= 100


def test_an_entry_larger_than_the_budget_is_never_admitted():
    # admitting it would evict everything else and then be evicted itself
    c = basecache.BaseCache(100)
    c.put("small", "S", 50)
    c.put("huge", "H", 500)
    assert c.get("huge") is None
    assert c.get("small") == "S"


def test_replacing_a_key_does_not_double_count_its_bytes():
    c = basecache.BaseCache(1000)
    c.put("k", "v1", 100)
    c.put("k", "v2", 100)
    assert c.get("k") == "v2"
    assert c.stats()["bytes"] == 100


def test_a_zero_budget_disables_the_cache_entirely():
    c = basecache.BaseCache(0)
    assert not c.enabled
    c.put("k", "v", 1)
    assert c.get("k") is None
    assert c.stats()["entries"] == 0


def test_clear_empties_the_store():
    c = basecache.BaseCache(1000)
    c.put("k", "v", 10)
    c.clear()
    assert c.get("k") is None
    assert c.stats()["bytes"] == 0
```

### Step 2: Run test to verify it fails

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.basecache'`

### Step 3: Write minimal implementation

Create `app/basecache.py`:

```python
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
```

### Step 4: Run test to verify it passes

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py`
Expected: PASS (7 passed)

### Step 5: Commit

```bash
git add app/basecache.py tests/test_base_cache.py
git commit -m "Add a byte-budgeted LRU for the painted terrain base

The store only -- what may be reused, and when, is the key, and that belongs
next to the painter it describes. Bounded by bytes rather than entries because
an entry swings ~20x between a 96 dpi draft and a 200 dpi High-relief refine.

An entry larger than the whole budget is refused rather than admitted: taking it
would evict everything else and then be evicted itself on the next put."
```

---

## Task 2: Extract `_luminance`

The cache stores pixels, not the `lum` plane — `lum` is a pure function of the pixels,
so recomputing it on a hit is byte-identical and avoids caching a float64 plane ~2.7×
the size of the uint8 sheet it comes from. That needs one shared definition.

Files:
- Modify: `app/render.py` (the tail of `_paint_base`, ~line 2000)
- Test: `tests/test_base_cache.py`

### Step 1: Write the failing test

Append to `tests/test_base_cache.py`:

```python
def test_luminance_matches_the_inline_expression():
    """_paint_base used to compute this inline. It is now shared with the cache-hit
    path, and the two must be the same expression or a hit would light markers
    differently from a cold render."""
    from app import render
    rgb = np.random.default_rng(0).integers(0, 256, (40, 30, 3), dtype=np.uint8)
    want = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0
    assert np.array_equal(render._luminance(rgb), want)
```

### Step 2: Run test to verify it fails

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py -k luminance`
Expected: FAIL — `AttributeError: module 'app.render' has no attribute '_luminance'`

### Step 3: Write minimal implementation

In `app/render.py`, add above `_paint_base`:

```python
def _luminance(rgb):
    """The marker-contrast luminance plane of a painted sheet (Rec. 709 weights). ONE
    definition, because it is now computed in two places: at the end of a cold
    _paint_base, and again from a CACHED base. It is a pure function of the pixels, so
    recomputing on a cache hit is byte-identical -- and far cheaper than storing a
    float64 plane ~2.7x the size of the uint8 sheet it derives from."""
    return (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]) / 255.0
```

Then replace the last two lines of `_paint_base`:

```python
    rgb = np.asarray(himg.convert("RGB"))
    lum = _luminance(rgb)
    return rgb, lum, ctx
```

### Step 4: Run tests to verify they pass

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py tests/test_markers.py tests/test_render.py`
Expected: PASS

### Step 5: Commit

```bash
git add app/render.py tests/test_base_cache.py
git commit -m "Extract _luminance so the cache-hit path shares one definition

lum is a pure function of the painted pixels, so a cached base can recompute it
byte-identically instead of storing a float64 plane ~2.7x the size of the uint8
sheet it comes from. One expression, two call sites, no chance of drift."
```

---

## Task 3: The plate fingerprint

Files:
- Modify: `app/render.py`
- Test: `tests/test_base_cache.py`

### Step 1: Write the failing test

```python
def test_plate_fingerprint_changes_when_an_asset_is_rebuilt(tmp_path):
    """Rebuilding a region must invalidate the cache. (mtime_ns, size) rather than a
    content hash: hashing a 188 MB DEM on every proof would cost more than the render
    the cache exists to skip."""
    from app import render
    cfg = {"dem_path": "dem.tif"}
    (tmp_path / "dem.tif").write_bytes(b"one")
    first = render._plate_fingerprint(str(tmp_path), cfg)
    assert first == render._plate_fingerprint(str(tmp_path), cfg)   # stable
    (tmp_path / "dem.tif").write_bytes(b"two-different-length")
    assert render._plate_fingerprint(str(tmp_path), cfg) != first


def test_plate_fingerprint_tolerates_a_missing_asset(tmp_path):
    # labels.json / landcover.tif are optional; absence is part of the identity
    from app import render
    fp = render._plate_fingerprint(str(tmp_path), {"dem_path": "dem.tif"})
    assert isinstance(fp, str) and fp
```

### Step 2: Run to verify it fails

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py -k fingerprint`
Expected: FAIL — `AttributeError: ... has no attribute '_plate_fingerprint'`

### Step 3: Implementation

In `app/render.py`, add `import hashlib` to the top imports (line 3 becomes
`import hashlib, json, math as _m, os, threading`) and change
`from app import provenance` to `from app import provenance, serialize`. Then add:

```python
def _plate_fingerprint(region_dir, cfg):
    """A cheap identity for the plate's assets so a rebuilt region invalidates the
    cache. (mtime_ns, size), NOT a content hash: hashing a 188 MB DEM on every proof
    would cost more than the render this cache exists to skip. A shared or
    cross-process cache would have to upgrade this."""
    parts = []
    for name in (cfg.get("dem_path", "dem.tif"),
                 cfg.get("landcover_path", "landcover.tif"),
                 "hydro.json", "labels.json"):
        try:
            st = os.stat(os.path.join(region_dir, name))
            parts.append(f"{name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{name}:-")          # an absent asset is part of the identity
    return "|".join(parts)
```

### Step 4: Run to verify it passes

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py -k fingerprint`
Expected: PASS

### Step 5: Commit

```bash
git add app/render.py tests/test_base_cache.py
git commit -m "Fingerprint a plate's assets so a rebuild invalidates the base cache

(mtime_ns, size) over the DEM, landcover and the two JSON assets. Not a content
hash: hashing a 188 MB DEM on every proof would cost more than the render the
cache exists to skip."
```

---

## Task 4: The cache key and its mask contract

This is the correctness centre of the change.

Files:
- Modify: `app/render.py`
- Test: `tests/test_base_cache.py`

### Step 1: Write the failing test

```python
from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _live_spec(**kw):
    """A spec with EVERYTHING switched on, so no field is inert and every one of them
    is expected to reach the key. A field masked only because the feature that reads it
    happens to be off would be a false pass."""
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    crop = (cx - 13500, cy - 18000, cx + 13500, cy + 18000)
    d = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
             print_w_in=9, print_h_in=12, native_resolution_m=10,
             tracks=[np.array([[crop[0] + 2000, crop[1] + 2000],
                               [crop[2] - 2000, crop[3] - 2000]])],
             track_days=["2026-05-01"],
             hotspots=[{"x": cx, "y": cy, "weight": 2}],
             title_text="GOLDEN", credit_text="USGS 3DEP", seed=7,
             contours=True, compass=True, biome=True, labels=True,
             label_place="smart", track_weave=True, track_color_by="elevation",
             profile=True, profile_rev=2, relief_rev=2, oblique=0.4,
             light_mode="journey", top_clear_frac=0.1, bottom_clear_frac=0.1)
    d.update(kw)
    return CompositionSpec(**d)


# One perturbation per field type. Explicit rather than clever, because a wrong
# perturbation here would make the guard below pass vacuously.
_PERTURB = {
    "crop": lambda s: dataclasses.replace(s, crop=tuple(v + 10.0 for v in s.crop)),
    "tracks": lambda s: dataclasses.replace(
        s, tracks=[np.asarray(t, float) + 7.0 for t in s.tracks]),
    "track_days": lambda s: dataclasses.replace(s, track_days=["2019-02-03"]),
    "hotspots": lambda s: dataclasses.replace(
        s, hotspots=list(s.hotspots) + [{"x": 1.0, "y": 2.0, "weight": 1}]),
    "track_rgb": lambda s: dataclasses.replace(s, track_rgb=(1, 2, 3)),
}


def _perturb(spec, name):
    if name in _PERTURB:
        return _PERTURB[name](spec)
    v = getattr(spec, name)
    if isinstance(v, bool):
        return dataclasses.replace(spec, **{name: not v})
    if isinstance(v, int):
        return dataclasses.replace(spec, **{name: v + 1})
    if isinstance(v, float):
        return dataclasses.replace(spec, **{name: v + 0.5})
    if isinstance(v, str):
        return dataclasses.replace(spec, **{name: v + "-x"})
    raise AssertionError(f"no perturbation defined for {name} ({type(v).__name__}) -- "
                         f"add one to _PERTURB so the guard below cannot pass vacuously")


def _key(spec, dpi=96):
    from app import render
    return render.base_cache_key(spec, dpi, REGION_DIR, _cfg())


def test_every_unmasked_spec_field_changes_the_key():
    """The guard that keeps this cache honest as the spec grows.

    Enumerating the dataclass means a field added next year is in this test the day it
    lands: either it is deliberately masked, or changing it MUST change the key. The
    failure direction is the point -- an unclassified field costs a cache miss (slow
    but correct), where an allowlist would serve stale terrain and the proof would stop
    predicting the print."""
    from app import render
    base = _live_spec()
    key = _key(base)
    masked = set(render.BASE_KEY_MASK_ALWAYS)
    for f in dataclasses.fields(CompositionSpec):
        alt = _perturb(base, f.name)
        if f.name in masked:
            assert _key(alt) == key, f"{f.name} is masked but still changed the key"
        else:
            assert _key(alt) != key, (
                f"{f.name} is not masked, so it may reach _paint_base -- it MUST be in "
                f"the key, or added to a mask list with a reason")


def test_the_unlabelled_mask_applies_only_when_place_names_are_off():
    """With labels on, _draw_labels runs INSIDE _paint_base: _label_keepout measures the
    cartouche/compass/profile stack (and, at profile_rev 2, the title and label point
    sizes through _title_block_metrics), and smart placement rasterizes the route as an
    obstacle. So the furniture and track fields reach the base -- but only then."""
    from app import render
    off = _live_spec(labels=False)
    on = _live_spec(labels=True)
    for name in render.BASE_KEY_MASK_UNLABELLED:
        assert _key(_perturb(off, name)) == _key(off), f"{name} keyed with labels off"
        assert _key(_perturb(on, name)) != _key(on), f"{name} not keyed with labels on"


def test_dpi_and_plate_are_part_of_the_key():
    s = _live_spec()
    assert _key(s, dpi=96) != _key(s, dpi=200)
```

### Step 2: Run to verify it fails

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py -k key`
Expected: FAIL — `AttributeError: ... has no attribute 'BASE_KEY_MASK_ALWAYS'`

### Step 3: Implementation

In `app/render.py`, after `_plate_fingerprint`:

```python
# ---- the base-layer cache key (the store is app/basecache.py) ----------------------
# Derived by MASKING, never by listing. The key is the serialized spec MINUS the fields
# that provably cannot reach _paint_base; everything else -- including a field added
# years from now -- stays in the key by default. That direction is the whole safety
# argument: an unclassified new field costs a cache MISS (slow but correct), where an
# allowlist would quietly serve stale terrain and the proof would stop predicting the
# print. tests/test_base_cache.py enumerates the dataclass to enforce it.
#
# ALWAYS safe: nothing reachable from _paint_base reads these. They are the route ink,
# the point symbols, and the photo frames -- painted by _paint_journey/_paint_overlays.
BASE_KEY_MASK_ALWAYS = (
    "track_rgb", "track_halo", "track_max_darken", "track_color_by", "track_weave",
    "marker_diameter_in", "marker_ring", "photo_frame_style", "photo_box_in",
    "keyline", "hotspots",
)
# Safe ONLY when place names are off. With spec.labels on, _draw_labels runs inside
# _paint_base and _label_keepout measures the bottom-left furniture stack -- which at
# profile_rev 2 reaches _profile_rect -> _furniture_stack_top -> _title_block_metrics,
# so the title/label point sizes, the credit line and the edition are in it too. And
# under label_place == "smart" the drawn route is a placement obstacle, so the track
# geometry and its width reach the base as well. Phase 2 of the plan dissolves this
# list by caching the sheet BEFORE labels are drawn.
BASE_KEY_MASK_UNLABELLED = (
    "title_text", "title_pt", "label_pt", "credit_text", "edition",
    "compass", "furniture_scale", "profile", "profile_height_in", "profile_rev",
    "tracks", "track_days", "track_width_pt",
)

def base_cache_key(spec, dpi, region_dir, cfg):
    """A stable digest of everything `_paint_base` can see for this (spec, dpi, plate).
    `spec` is the PAINT spec (post-bleed), because that is what _paint_base receives."""
    payload = serialize.spec_to_json(spec)
    for name in BASE_KEY_MASK_ALWAYS:
        payload.pop(name, None)
    if not spec.labels:
        for name in BASE_KEY_MASK_UNLABELLED:
            payload.pop(name, None)
    blob = json.dumps([payload, os.path.abspath(region_dir), float(dpi),
                       _plate_fingerprint(region_dir, cfg)],
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

### Step 4: Run to verify it passes

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py`
Expected: PASS

> If `test_every_unmasked_spec_field_changes_the_key` fails on a field you believe is
> inert, do **not** add it to a mask list to make the test green. Confirm by reading
> `_paint_base` and everything it calls; if it genuinely cannot reach the base, add it
> with a comment saying why. A wrong entry here is a stale poster.

### Step 5: Commit

```bash
git add app/render.py tests/test_base_cache.py
git commit -m "Derive the base-cache key by masking, not by listing

The key is the serialized spec minus the fields that provably cannot reach
_paint_base. A field added later lands in the key by default, so the worst case
is a cache miss rather than a stale terrain layer under a fresh route -- which
would be a proof that no longer predicts the print.

The mask is conditional on spec.labels for a real reason: _draw_labels runs
inside _paint_base, and _label_keepout measures the furniture stack -- at
profile_rev 2 that reaches _title_block_metrics, so the title/label point sizes,
the credit line and the edition are base inputs too. Under smart placement the
drawn route is a placement obstacle, so track geometry is as well.

A dataclass-enumerating test asserts both directions, so a spec field added in
future is classified the day it lands."
```

---

## Task 5: Route `_paint_base` through the cache

Files:
- Modify: `app/render.py`
- Test: `tests/test_base_cache.py`

### Step 1: Write the failing test

```python
CACHE_MATRIX = {
    "plain": {},
    "contours": {"contours": True},
    "labels_anchor": {"labels": True, "label_place": "anchor"},
    "labels_smart": {"labels": True, "label_place": "smart"},
    "oblique": {"oblique": 0.6},
    "oblique_labels": {"oblique": 0.6, "labels": True, "contours": True},
    "biome": {"biome": True},
    "bleed": {"bleed_in": 0.125},
    "journey": {"light_mode": "journey", "sun_azimuth_deg": 140.0,
                "sun_altitude_deg": 22.0, "golden_strength": 0.8},
}


@pytest.mark.parametrize("name", sorted(CACHE_MATRIX))
def test_a_cache_hit_is_pixel_identical_to_a_cold_render(name):
    """The cache may only ever be invisible. Anything else is a proof that stops
    predicting the print."""
    from app import basecache, render
    spec = _live_spec(labels=False, oblique=0.0, contours=False, biome=False,
                      profile=False, light_mode="archival", label_place="anchor",
                      **CACHE_MATRIX[name])
    cold = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR))
    cache = basecache.BaseCache(400_000_000)
    warm = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR,
                                       base_cache=cache))          # miss, fills
    hit = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR,
                                      base_cache=cache))           # hit
    assert cache.stats()["hits"] == 1
    assert np.array_equal(cold, warm)
    assert np.array_equal(cold, hit)


def test_a_route_knob_hits_the_cache_and_a_terrain_knob_misses_it():
    from app import basecache, render
    spec = _live_spec(labels=False)
    cache = basecache.BaseCache(400_000_000)
    render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=cache)
    render.rasterize(dataclasses.replace(spec, track_rgb=(10, 20, 30)), 96,
                     region_dir=REGION_DIR, base_cache=cache)
    assert cache.stats()["hits"] == 1, "a route-ink knob must reuse the terrain"
    render.rasterize(dataclasses.replace(spec, shadow_strength=0.1), 96,
                     region_dir=REGION_DIR, base_cache=cache)
    assert cache.stats()["hits"] == 1, "a terrain knob must NOT reuse it"


def test_the_cached_arrays_are_read_only():
    """A tripwire, not a guarantee: nothing writes to the base today (_ink_tracks
    copies to float, the vector painters build their own images), so freezing costs
    nothing -- and turns a future in-place write from a silently poisoned cache into an
    immediate exception."""
    from app import basecache, render
    spec = _live_spec(labels=False, oblique=0.5)
    cache = basecache.BaseCache(400_000_000)
    render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=cache)
    rgb, ctx = next(iter(cache._entries.values()))
    assert not rgb.flags.writeable
    assert ctx is not None and not ctx.elev.flags.writeable
    with pytest.raises(ValueError):
        rgb[0, 0, 0] = 1


def test_a_disabled_cache_is_the_pre_cache_path():
    from app import basecache, render
    spec = _live_spec(labels=False)
    off = basecache.BaseCache(0)
    a = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=off))
    b = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR))
    assert np.array_equal(a, b)
    assert off.stats()["entries"] == 0


def test_a_failing_render_is_not_cached():
    """The off-DEM guard lives inside _paint_base. A hit implies it passed for exactly
    this key (it reads only crop + plate + oblique band), and a failure must re-raise
    every time rather than being remembered."""
    from app import basecache, render
    from app.spec import OffDemError
    cfg = _cfg()
    bx = cfg["bounds"]
    off_plate = (bx[2] + 60000, bx[3] + 60000, bx[2] + 87000, bx[3] + 96000)
    spec = _live_spec(labels=False, crop=off_plate)
    cache = basecache.BaseCache(400_000_000)
    for _ in range(2):
        with pytest.raises(OffDemError):
            render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=cache)
    assert cache.stats()["entries"] == 0
```

### Step 2: Run to verify it fails

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py -k cache`
Expected: FAIL — `TypeError: rasterize() got an unexpected keyword argument 'base_cache'`

### Step 3: Implementation

In `app/render.py`, add after `base_cache_key`:

```python
def _entry_bytes(rgb, ctx):
    """What one cached base costs. The plan-oblique context is the swing factor: its
    padded elevation and winner buffers are several times the trimmed sheet."""
    n = int(rgb.nbytes)
    if ctx is not None:
        n += int(ctx.elev.nbytes) + int(ctx.winner.nbytes)
    return n

def _freeze(rgb, ctx):
    """Mark a cached base read-only. Nothing downstream writes to it today, so this
    costs nothing -- and it converts a future in-place write from a silently poisoned
    cache into an immediate exception. Applied on the cold path too, so the tripwire
    fires on the first render rather than only on a later hit."""
    rgb.flags.writeable = False
    if ctx is not None:
        ctx.elev.flags.writeable = False
        ctx.winner.flags.writeable = False

def _base_layer(paint, dpi, region_dir, cfg, hydro, labels, trim, base_cache):
    """`_paint_base` through the cache when one is supplied. `base_cache=None` -- every
    caller except the two proof endpoints -- is the pre-cache path, unchanged.

    On a hit `lum` is recomputed from the cached pixels rather than stored: it is a
    pure function of them, so the hit is byte-identical to a cold render, and a float64
    plane would be ~2.7x the size of the uint8 sheet it derives from.

    A render that RAISES (the off-DEM guard) is never cached -- and need not be, since
    the guard reads only crop + plate + oblique band, all of which are in the key, so a
    hit already implies it passed."""
    if base_cache is None or not base_cache.enabled:
        return _paint_base(paint, dpi, region_dir, cfg, hydro=hydro, labels=labels,
                           trim=trim)
    key = base_cache_key(paint, dpi, region_dir, cfg)
    hit = base_cache.get(key)
    if hit is not None:
        rgb, ctx = hit
        return rgb, _luminance(rgb), ctx
    rgb, lum, ctx = _paint_base(paint, dpi, region_dir, cfg, hydro=hydro, labels=labels,
                                trim=trim)
    _freeze(rgb, ctx)
    base_cache.put(key, (rgb, ctx), _entry_bytes(rgb, ctx))
    return rgb, lum, ctx
```

Then change `rasterize`'s signature and its `_paint_base` call:

```python
def rasterize(spec: CompositionSpec, dpi: int, region_dir: str,
              watermark: bool = False, hydro=None, cfg=None, labels=None,
              base_cache=None) -> Image.Image:
```

```python
    base_rgb, lum, ctx = _base_layer(paint, dpi, region_dir, cfg, hydro=hydro,
                                     labels=labels, trim=trim, base_cache=base_cache)
```

### Step 4: Run to verify it passes

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py`
Expected: PASS

Then confirm nothing else moved:

Run: `.venv/bin/python -m pytest -q -m "not slow and not serial"`
Expected: PASS

### Step 5: Commit

```bash
git add app/render.py tests/test_base_cache.py
git commit -m "Serve _paint_base from the cache when one is supplied

base_cache=None is the pre-cache path exactly, so timelapse, mockups, the
wallpaper bundle and the final path are untouched by construction.

A hit recomputes lum from the cached pixels instead of storing it -- pure
function of them, so byte-identical, and it avoids caching a float64 plane ~2.7x
the size of the uint8 sheet. Cached arrays are frozen read-only on the cold path
too, so an accidental in-place write fails on the first render rather than
silently poisoning a later hit.

Failing renders are never cached: the off-DEM guard reads only crop + plate +
oblique band, all of which are in the key, so a hit already implies it passed."
```

---

## Task 6: Wire it into the proof endpoints

Files:
- Modify: `app/main.py`
- Test: `tests/test_base_cache.py`

### Step 1: Write the failing test

```python
def test_the_proof_endpoint_reuses_the_terrain_across_a_style_knob():
    """End to end: two proofs of the same composition differing only in route ink must
    paint the terrain once."""
    from tests.test_main import _client, _upload, _crop
    from app import main as main_mod
    main_mod.BASE_CACHE.clear()
    before = main_mod.BASE_CACHE.stats()["hits"]
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0),
            "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    assert c.post("/api/proof", data={**data, "track_color": "#b24c2b"}).status_code == 200
    assert main_mod.BASE_CACHE.stats()["hits"] > before


def test_the_final_path_does_not_use_the_cache():
    """A final renders at 300 dpi -- a different key, so it could never hit -- and a
    39 MP entry would evict everything the proof loop depends on."""
    import inspect
    from app import main as main_mod
    src = inspect.getsource(main_mod._render_to_blob)
    assert "base_cache" not in src
```

> Check the actual form field name for the track colour in `app/main.py`'s `/api/proof`
> signature before running (`track_color` vs `color`) and adjust.

### Step 2: Run to verify it fails

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py -k proof_endpoint`
Expected: FAIL — `AttributeError: module 'app.main' has no attribute 'BASE_CACHE'`

### Step 3: Implementation

In `app/main.py`, add `basecache` to the `from app import ...` line, then after the
`PROOF_QUEUE` definition:

```python
# Base-layer cache: ~90% of a proof is the terrain layer, and most style knobs cannot
# change it (see docs/superpowers/plans/2026-07-26-base-layer-cache.md). Bounded by
# BYTES because an entry swings ~20x between a 96 dpi draft and a 200 dpi High-relief
# refine. Wired into the two PROOF paths only: a final renders at a different dpi so it
# could never hit, and a 39 MP entry would evict everything the studio depends on.
# TECOPA_BASE_CACHE_MB=0 disables it.
BASE_CACHE = basecache.BaseCache(
    int(float(os.environ.get("TECOPA_BASE_CACHE_MB", basecache.DEFAULT_MB)) * 1_000_000))
```

In `/api/proof` (~line 1029):

```python
        img = render.rasterize(spec, dpi=_proof_dpi(spec), region_dir=region.dir,
                               watermark=True, cfg=region.cfg, base_cache=BASE_CACHE)
```

In `_render_refine_to_blob`, add the parameter and use it:

```python
def _render_refine_to_blob(spec, region_dir, key, cfg=None, base_cache=None):
    ...
    img = render.rasterize(spec, dpi=dpi, region_dir=region_dir,
                           watermark=True, cfg=cfg, base_cache=base_cache)
```

and at the submit site (~line 1083):

```python
    jid = PROOF_QUEUE.submit(_render_refine_to_blob, spec, region.dir, key, region.cfg,
                             BASE_CACHE)
```

### Step 4: Run to verify it passes

Run: `.venv/bin/python -m pytest -q tests/test_base_cache.py tests/test_main.py tests/test_proof_refine.py`
Expected: PASS

### Step 5: Commit

```bash
git add app/main.py tests/test_base_cache.py
git commit -m "Wire the base cache into the two proof paths

The synchronous draft and the queued refine, and nothing else. A final renders
at 300 dpi so it could never hit the key anyway, and a 39 MP entry would evict
everything the studio depends on.

Budget via TECOPA_BASE_CACHE_MB (default 256, 0 disables)."
```

---

## Task 7: Classify the slow tests and note the module

Files:
- Modify: `tests/conftest.py`, `CLAUDE.md`

### Step 1–3

In `tests/conftest.py`, add to `_SLOW_TESTS`:

```python
    "test_base_cache": {
        "test_a_cache_hit_is_pixel_identical_to_a_cold_render",
        "test_a_route_knob_hits_the_cache_and_a_terrain_knob_misses_it",
        "test_the_cached_arrays_are_read_only",
        "test_a_disabled_cache_is_the_pre_cache_path",
        "test_a_failing_render_is_not_cached",
        "test_the_proof_endpoint_reuses_the_terrain_across_a_style_knob",
    },
```

In `CLAUDE.md`, add to the repo map table after the `app/render.py` row:

```
| `app/basecache.py` | the proof loop's terrain cache — what may be reused is `render.base_cache_key` |
```

### Step 4: Full verification

```bash
.venv/bin/python -m pytest -q -m "not slow and not serial"   # fast tier
.venv/bin/python -m pytest -q -m "slow and not serial"       # full renders
.venv/bin/python -m pytest -q -m serial                      # the orphan drill
```
Expected: PASS on all three. The orphan drill is the outer guard — it reprints a golden
poster byte-identically, and it does not go through the cache, so it proves the
refactor left the painter alone.

### Step 5: Commit

```bash
git add tests/conftest.py CLAUDE.md
git commit -m "Classify the base-cache render tests as slow and map the module"
```

---

# Phase 2 — move the cut point before labels

Only start this once Phase 1 has run in real use. It deletes
`BASE_KEY_MASK_UNLABELLED` entirely: with labels drawn *after* the cached unit, the
furniture and track fields stop being base inputs, so every non-terrain knob hits the
cache whether place names are on or off.

The cut is already in the right place — labels are the last thing `_paint_base` draws,
immediately before `lum` is computed — so this is a re-entry point, not a reordering.
Labels cost 2.2–2.9% of the base, so redrawing them per request is nearly free.

## Task 8: Split `_paint_base` into terrain + labels

Extract everything up to and including `_draw_hydro` into `_paint_terrain(...) -> (himg, ctx)`
returning the RGBA image. `_paint_base` becomes:

```python
def _paint_base(spec, dpi, region_dir, cfg, hydro=None, labels=None, trim=None):
    himg, ctx = _paint_terrain(spec, dpi, region_dir, cfg, hydro=hydro)
    himg = _apply_labels(himg, spec, dpi, region_dir, cfg, labels, ctx, trim)
    rgb = np.asarray(himg.convert("RGB"))
    return rgb, _luminance(rgb), ctx
```

Verify with the golden matrix and the orphan drill that this is byte-identical before
touching the cache. **One thing to check explicitly:** `_paint_terrain` returns RGBA and
`_apply_labels` draws onto it; if the cache stores RGB to halve the entry, assert in a
test that the alpha channel is uniformly 255 at that point, or store RGBA.

## Task 9: Cache the terrain, redraw labels per request

`_base_layer` caches `(terrain_rgb, ctx)` and on every call — hit or miss — runs
`_apply_labels` and `_luminance`. Delete `BASE_KEY_MASK_UNLABELLED` and fold the
unconditional half into `BASE_KEY_MASK_ALWAYS`, adding the furniture and track fields.

## Task 10: Tighten the tests

`test_the_unlabelled_mask_applies_only_when_place_names_are_off` is replaced by one
asserting the furniture and track fields never key the base. Extend the pixel-equality
matrix to assert a hit with `labels=True, label_place="smart"` while the *track width*
changes — the case Phase 1 cannot serve.

Expected effect after Phase 2: the ~1.5 s knob response applies to all 25 non-terrain
knobs, labels on or off.

---

## Risks and how they are covered

| Risk | Cover |
|---|---|
| A spec field added later isn't classified and the cache serves stale terrain | Mask-based key (unclassified ⇒ in the key ⇒ miss) + the dataclass-enumerating test |
| Something downstream mutates a cached array | `_freeze` on the cold path too, so it fails on the first render; a test asserts read-only |
| A rebuilt plate serves the old terrain | `_plate_fingerprint` in the key; a test rebuilds an asset and asserts the key moves |
| The off-DEM guard is skipped on a hit | The guard's inputs are all in the key, so a hit implies it passed; failures are never cached; a test asserts a bad crop re-raises every time |
| Memory pressure on the operator's Mac | Byte budget, default 256 MB, `TECOPA_BASE_CACHE_MB=0` disables; final/bundle paths excluded |
| The refactor moves pixels | The existing golden matrix and the orphan drill, neither of which goes through the cache |
