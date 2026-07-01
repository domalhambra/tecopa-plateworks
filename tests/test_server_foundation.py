# tests/test_server_foundation.py
# v1.3 seams: serialization, pluggable session store (incl. SQLite persistence),
# blob storage, and the render job queue. All DEM-free, so they run on a fresh clone.
import time
import numpy as np
from app.ingest import Track
from app.spec import CompositionSpec
from app import serialize, store, blobs, jobs

def _session():
    crop = (1000.0, 2000.0, 4000.0, 6000.0)
    tracks = [Track("t-0", np.array([[1100.0, 2100.0], [3900.0, 5900.0]]), "2024-06-01")]
    spec = CompositionSpec(region_id="lassen_ca", crs="EPSG:32610", crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[t.coords for t in tracks],
                           hotspots=[{"x": 2500.0, "y": 4000.0, "weight": 3, "label": "Camp"}],
                           seed=7, title_text="LASSEN")
    return {"region_id": "lassen_ca", "tracks": tracks,
            "hotspots": [{"x": 2500.0, "y": 4000.0, "weight": 3, "label": "Camp"}],
            "spec": spec}

def test_session_round_trips_through_json():
    data = _session()
    back = serialize.load_session(serialize.dump_session(data))
    assert back["region_id"] == "lassen_ca"
    assert back["hotspots"] == data["hotspots"]
    assert np.allclose(back["tracks"][0].coords, data["tracks"][0].coords)
    assert back["tracks"][0].day == "2024-06-01"
    # spec survives exactly enough to render the same picture
    assert back["spec"].crop == data["spec"].crop
    assert back["spec"].title_text == "LASSEN"
    assert np.allclose(back["spec"].tracks[0], data["spec"].tracks[0])

def test_memory_store_basic():
    s = store.MemoryStore()
    sid = s.create(_session())
    assert s.has(sid) and s.get(sid)["region_id"] == "lassen_ca"
    s.update(sid, hotspots=[])
    assert s.get(sid)["hotspots"] == []

def test_memory_store_get_is_deep_isolated():
    # red-team V1-3: mutating a get()'d session (nested hotspots) must NOT leak into
    # stored state -- the shallow copy.copy shared the list and diverged from SQLite.
    s = store.MemoryStore()
    sid = s.create({"region_id": "r", "hotspots": [{"label": "A"}], "tracks": [], "spec": None})
    got = s.get(sid)
    got["hotspots"][0]["label"] = "MUTATED"
    assert s.get(sid)["hotspots"][0]["label"] == "A"

def test_memory_store_create_and_update_dont_alias_caller():
    s = store.MemoryStore()
    src = {"region_id": "r", "hotspots": [{"label": "A"}], "tracks": [], "spec": None}
    sid = s.create(src)
    src["hotspots"][0]["label"] = "MUTATED"          # mutate the original after create
    assert s.get(sid)["hotspots"][0]["label"] == "A"
    hs = [{"label": "B"}]
    s.update(sid, hotspots=hs)
    hs[0]["label"] = "MUTATED"                        # mutate after write-back
    assert s.get(sid)["hotspots"][0]["label"] == "B"

def test_sqlite_store_persists_across_instances(tmp_path):
    path = str(tmp_path / "t.db")
    sid = store.SqliteStore(path).create(_session())
    # a brand-new store object on the same file still sees the session (survives restart)
    s2 = store.SqliteStore(path)
    assert s2.has(sid)
    got = s2.get(sid)
    assert got["region_id"] == "lassen_ca"
    assert np.allclose(got["tracks"][0].coords, _session()["tracks"][0].coords)
    assert got["spec"].title_text == "LASSEN"

def test_make_store_default_is_memory():
    assert isinstance(store.make_store(), store.MemoryStore)
    assert isinstance(store.make_store("sqlite", path=":memory:"), store.SqliteStore)

def test_blobs_put_path_exists_and_guards_escape(tmp_path):
    b = blobs.LocalBlobs(str(tmp_path / "blobs"))
    b.put("sess/final.png", b"PNGDATA")
    assert b.exists("sess/final.png")
    assert open(b.path("sess/final.png"), "rb").read() == b"PNGDATA"
    import pytest
    with pytest.raises(ValueError):
        b.path("../escape.png")

def test_blobs_delete_is_idempotent(tmp_path):
    b = blobs.LocalBlobs(str(tmp_path / "blobs"))
    b.put("s/final.png", b"X")
    b.delete("s/final.png")
    assert not b.exists("s/final.png")
    b.delete("s/final.png")          # deleting a missing key is a no-op, not an error

def test_blobs_ttl_sweep_evicts_old_and_prunes_dirs(tmp_path):
    # red-team V1-8: finals must not accumulate forever. A blob older than the TTL is
    # swept and its now-empty session dir pruned; a fresh blob survives.
    b = blobs.LocalBlobs(str(tmp_path / "blobs"), ttl_seconds=3600)
    old_p = b.put("old/final.png", b"X")
    b.put("fresh/final.png", b"Y")
    stale = time.time() - 100_000
    import os
    os.utime(old_p, (stale, stale))
    assert b.sweep() == 1
    assert not b.exists("old/final.png") and b.exists("fresh/final.png")
    assert not os.path.isdir(os.path.dirname(old_p))    # empty session dir pruned

def test_job_queue_runs_and_reports_done():
    q = jobs.ThreadJobQueue()
    jid = q.submit(lambda a, b: a + b, 2, 3)
    for _ in range(200):
        if q.status(jid)["state"] in ("done", "error"):
            break
        time.sleep(0.01)
    s = q.status(jid)
    assert s["state"] == "done" and s["result"] == 5

def test_job_queue_captures_error():
    q = jobs.ThreadJobQueue()
    def boom():
        raise ValueError("nope")
    jid = q.submit(boom)
    for _ in range(200):
        if q.status(jid)["state"] in ("done", "error"):
            break
        time.sleep(0.01)
    s = q.status(jid)
    assert s["state"] == "error" and "nope" in s["error"]

def test_job_queue_evicts_finished_after_ttl():
    # red-team V1-8: finished job records must not grow unbounded. A done record older
    # than the TTL is evicted the next time a job is submitted.
    import pytest
    q = jobs.ThreadJobQueue(ttl_seconds=3600)
    jid = q.submit(lambda: 1)
    for _ in range(200):
        if q.status(jid)["state"] == "done":
            break
        time.sleep(0.01)
    assert q.status(jid)["state"] == "done"
    with q._lock:                                   # backdate so it is past the TTL
        q._jobs[jid]["finished"] = time.time() - 100_000
    q.submit(lambda: 2)                             # submit triggers the eviction sweep
    with pytest.raises(KeyError):
        q.status(jid)
