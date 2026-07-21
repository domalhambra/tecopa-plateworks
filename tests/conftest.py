# tests/conftest.py
"""Make the DEM-gated integration suites runnable on a fresh clone / in CI.

The real 3DEP DEMs are large and gitignored (see region_prep.py), so historically
the endpoint / render / registration suites skipped everywhere except a machine
that had run region_prep.py. That is the highest-value 29% of the suite silently
not running (red-team V1-4).

This module hydrates every built region with a *tiny synthetic* DEM whose bounds
match its region.json exactly (single source of truth), a deterministic smooth
elevation surface inside [elevation_min, elevation_max], and a `synthetic=1`
GeoTIFF tag so downstream code can tell it apart from a real DEM. It only builds a
DEM that is missing, so a machine with real 3DEP data is left untouched. The file
stays gitignored — it is a test artifact, never committed.
"""
from __future__ import annotations
import json
import os
import tempfile

# Isolate the app's writable stores BEFORE any test module imports app.main: the
# endpoint tests used to write finals into the repo's live blobs/ and uploads/
# (417 MB accumulated) and every put() swept the operator's real store (red-team).
#
# Under pytest-xdist each worker MUST get its own store: the workers inherit the
# controller's environment (where the setdefault below already ran), so without this
# they would all share one blobs/ dir and one worker's TTL/orphan sweep would evict
# another worker's in-flight result. PYTEST_XDIST_WORKER ("gw0", "gw1", …) is set in
# each worker's env before conftest imports, so key the private store on it.
_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _worker:
    os.environ["TECOPA_BLOBS"] = tempfile.mkdtemp(prefix=f"tecopa-test-blobs-{_worker}-")
    os.environ["TECOPA_UPLOADS"] = tempfile.mkdtemp(prefix=f"tecopa-test-uploads-{_worker}-")
else:
    os.environ.setdefault("TECOPA_BLOBS",
                          tempfile.mkdtemp(prefix="tecopa-test-blobs-"))
    os.environ.setdefault("TECOPA_UPLOADS",
                          tempfile.mkdtemp(prefix="tecopa-test-uploads-"))

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds

REGIONS_ROOT = os.environ.get("TECOPA_REGIONS", "regions")

# Coarse on purpose: a synthetic DEM only has to cover the region and read cleanly
# through rasterio's windowed/boundless path. The zoom cap is judged against
# region.json's native_resolution_m, not the DEM's own grid, so a coarse synthetic
# grid still exercises the same code paths as a 10 m real DEM.
_SYNTH_NX = 240
_SYNTH_NY = 300


def _synthetic_surface(nx: int, ny: int, emin: float, emax: float) -> np.ndarray:
    """A smooth, fully-finite elevation field in [emin, emax]. Deterministic (no RNG)
    so the committed tests are stable and relief/hillshade have real gradients to
    shade — a flat plane would make the hillshade azimuth test meaningless."""
    v, u = np.mgrid[0:ny, 0:nx].astype("float64")
    u /= max(1, nx - 1)
    v /= max(1, ny - 1)
    hills = 0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * u) * np.cos(2 * np.pi * 1.5 * v)
    peak = np.exp(-(((u - 0.5) ** 2 + (v - 0.5) ** 2) / 0.08))
    s = np.clip(0.6 * hills + 0.4 * peak, 0.0, 1.0)
    return (emin + (emax - emin) * s).astype("float32")


def _build_synthetic_dem(region_dir: str, cfg: dict) -> None:
    west, south, east, north = cfg["bounds"]
    emin = float(cfg.get("elevation_min", 1000.0))
    emax = float(cfg.get("elevation_max", 2000.0))
    if emax <= emin:
        emax = emin + 1000.0
    data = _synthetic_surface(_SYNTH_NX, _SYNTH_NY, emin, emax)
    transform = from_bounds(west, south, east, north, _SYNTH_NX, _SYNTH_NY)
    profile = dict(driver="GTiff", dtype="float32", count=1,
                   height=_SYNTH_NY, width=_SYNTH_NX, crs=cfg["crs"],
                   transform=transform, nodata=np.nan, tiled=True,
                   blockxsize=128, blockysize=128, compress="deflate")
    out = os.path.join(region_dir, cfg.get("dem_path", "dem.tif"))
    # Atomic write: under `pytest -n auto` several workers hydrate the SHARED regions/
    # tree at once, so build into a private temp file (same dir → same filesystem →
    # os.replace is atomic) and swap it in. A reader never sees a half-written DEM, and
    # two concurrent builders just race to a valid file (the loser's write is a no-op
    # overwrite). The GTiff driver is explicit, so the .tmp extension is irrelevant, and
    # build_overviews on a "w" dataset writes overviews INTERNALLY (no .ovr sidecar).
    tmp = f"{out}.{os.getpid()}.tmp"
    try:
        with rasterio.open(tmp, "w", **profile) as ds:
            ds.write(data, 1)
            ds.build_overviews([2, 4], Resampling.average)
            ds.update_tags(synthetic="1")   # marks this as a test DEM, not real terrain
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _hydrate_regions(root: str = REGIONS_ROOT) -> None:
    if not os.path.isdir(root):
        return
    for rid in sorted(os.listdir(root)):
        rdir = os.path.join(root, rid)
        cfg_path = os.path.join(rdir, "region.json")
        if not os.path.exists(cfg_path):
            continue
        with open(cfg_path) as f:
            cfg = json.load(f)
        dem_path = os.path.join(rdir, cfg.get("dem_path", "dem.tif"))
        if not os.path.exists(dem_path):
            _build_synthetic_dem(rdir, cfg)


def dem_is_synthetic(dem_path: str) -> bool:
    """True if the DEM at `dem_path` is one this harness built (tagged synthetic=1).
    Lets a real-terrain assertion (e.g. the control-point elevation test) skip when
    only a synthetic DEM is present."""
    if not os.path.exists(dem_path):
        return False
    with rasterio.open(dem_path) as ds:
        return ds.tags().get("synthetic") == "1"


# Hydrate at import (before any test module is collected or app.main is imported),
# so the integration suites find a DEM without needing a session fixture to run first.
_hydrate_regions()


# --- slow-tier policy (single source of truth) ---------------------------------------
# The PR tier runs `-m "not slow"` for minutes-fast feedback; the full suite runs on
# every push to main (each merge). Rather than scatter markers across ~20 files, classify here
# from `--durations` (on in pytest.ini) so the whole policy is auditable and updatable in
# one place. Threshold: a test costing >5s of render is "slow". Re-derive after adding
# heavy tests: `python -m pytest -n auto -m "not serial" --durations=0`.
import pytest  # noqa: E402

# Modules that are render-bound end to end — every test renders, so mark the whole file.
_SLOW_MODULES = {
    "test_editions", "test_oblique", "test_timelapse", "test_credit_and_names",
    "test_labels", "test_render", "test_mockups_api", "test_wallpaper_api",
    "test_output_fitness", "test_wallpaper",
}
# Otherwise-fast modules with a heavy subset: mark only the renders, so their fast
# validation/unit/security tests still run on PRs.
_SLOW_TESTS = {
    "test_main": {
        "test_async_final_via_job_queue", "test_final_blob_seam_srgb_and_dpi",
        "test_proof_then_final_happy_path", "test_async_final_pdf_via_job_queue",
        "test_contours_and_compass_flags_stamped_through_endpoint",
        "test_title_defaults_to_region_name_and_dash_suppresses",
        "test_reupload_after_proof_requires_reproof",
        "test_set_markers_updates_and_invalidates_spec",
        "test_move_marker_invalidates_spec", "test_final_unknown_format_is_422",
        "test_style_knobs_stamped_through_endpoint",
        "test_track_days_stamped_through_endpoint",
        "test_upload_multiple_files_accumulate",
    },
    "test_provenance": {
        "test_frozen_v1_manifest_loads_validates_and_reprints",
        "test_frozen_photo_manifest_reprints_its_embedded_photo",
        "test_reprint_drops_a_crafted_photo_path",
        "test_reprint_restamps_the_region_pack_byte_identically",
        "test_reprint_is_pixel_identical_to_the_final",
        "test_embedded_photo_reprints_after_the_uploads_dir_is_wiped",
        "test_final_carries_the_note_and_it_is_stable_across_renders",
        "test_embed_spec_false_omits_the_manifest",
        "test_share_copy_carries_no_text_chunks_at_all",
        "test_inspect_reports_verified_for_a_runtime_final",
        "test_final_embeds_a_reprintable_manifest_by_default",
        "test_final_manifest_carries_the_region_pack",
        "test_final_embeds_the_photo_as_bytes_not_a_path",
        "test_reprint_inspect_returns_provenance_without_rendering",
        "test_pdf_final_carries_no_manifest",
    },
    "test_mockups": {
        "test_lightsweep_starts_home_and_counts", "test_portrait_and_landscape_fit",
        "test_sizes_exact_and_jpeg_magic", "test_two_runs_byte_equal",
    },
    "test_profile_rev": {
        "test_new_proofs_stamp_rev_2_and_the_field_is_enum_gated",
        "test_rev1_render_unchanged_by_the_refactor",
        "test_rev2_labels_feet_and_render_differs_from_rev1",
    },
    "test_journey_light": {
        "test_journey_light_film_deterministic_and_moves",
        "test_journey_composes_with_high_relief",
        "test_journey_proof_stamps_resolved_sun_and_differs",
        "test_journey_changes_render_and_is_deterministic",
        "test_coloring_off_is_noop_on_and_changes_track",
        "test_profile_off_is_noop_on_and_draws",
        "test_journey_light_film_is_share_twin_only", "test_archival_is_strict_noop",
    },
    "test_smart_labels_and_weave": {
        "test_smart_labels_are_dpi_stable",
        "test_anchor_mode_still_drops_a_colliding_label",
        "test_smart_mode_places_a_colliding_label",
    },
    "test_proof_refine": {
        "test_refine_after_reproof_reflects_the_new_spec",
        "test_refine_crops_the_bleed_band_like_the_draft",
        "test_refine_renders_the_stamped_sheet_at_refine_dpi",
        "test_wallpaper_refine_reaches_native_device_pixels",
    },
    "test_plates": {
        "test_verify_poster_verified_then_mismatch",
        "test_verify_poster_pre_pack_and_region_missing",
    },
    "test_bleed": {
        "test_pdf_page_grows_by_the_bleed",
        "test_bleed_render_is_bigger_and_deterministic",
        "test_proof_is_trim_only_but_stamped_spec_keeps_the_bleed",
    },
    "test_biome": {
        "test_rasterize_biome_tints_with_landcover",
        "test_rasterize_biome_falls_back_without_landcover",
    },
}


def pytest_collection_modifyitems(config, items):
    for it in items:
        stem = it.path.stem                          # e.g. "test_main"
        base = getattr(it, "originalname", None) or it.name.split("[")[0]  # strip params
        if stem in _SLOW_MODULES or base in _SLOW_TESTS.get(stem, ()):
            it.add_marker(pytest.mark.slow)
