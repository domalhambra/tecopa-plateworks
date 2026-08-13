# The coin spin: the plate turning under a spotlight, as a social video.
# Share-class (no manifest), but still held to the render rules that matter for a
# marketing asset: deterministic, actually rotating, and lit like a spotlight.
import numpy as np
from PIL import Image

from scripts.render_coinspin import coin_webp, render_coin_frames
from scripts.render_model import DISC_RINGS, DISC_SEGMENTS, plate_mesh


def _art(w=300, h=400):
    """A recognizable asymmetric test card (gradient + bright quadrant)."""
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 0] = np.linspace(30, 220, w, dtype=np.uint8)[None, :]
    a[..., 1] = np.linspace(200, 40, h, dtype=np.uint8)[:, None]
    a[: h // 3, : w // 3, 2] = 230
    return Image.fromarray(a, "RGB")


def test_mesh_is_the_glb_mesh():
    # the coin renders the SAME object the landing page's <model-viewer> orbits
    pos, nrm, uv, idx, top = plate_mesh(_art())
    grid = 1 + DISC_RINGS * DISC_SEGMENTS
    assert top == grid
    assert len(pos) == 2 * grid + 2 * DISC_SEGMENTS      # top + back + rim wall
    assert len(nrm) == len(uv) == len(pos)
    assert idx.max() < len(pos)


def test_frames_shape_and_count():
    frames = render_coin_frames(_art(), n_frames=4, px=120)
    assert len(frames) == 4
    assert all(f.size == (120, 120) and f.mode == "RGB" for f in frames)


def test_deterministic():
    a = render_coin_frames(_art(), n_frames=2, px=100)
    b = render_coin_frames(_art(), n_frames=2, px=100)
    assert all(np.array_equal(np.asarray(x), np.asarray(y)) for x, y in zip(a, b))


def test_it_actually_rotates():
    frames = render_coin_frames(_art(), n_frames=4, px=120)
    assert not np.array_equal(np.asarray(frames[0]), np.asarray(frames[1]))
    # a quarter turn on shows the edge, not a mirror of the face
    assert not np.array_equal(np.asarray(frames[1]), np.asarray(frames[3]))


def test_spotlight_look():
    f0 = np.asarray(render_coin_frames(_art(), n_frames=1, px=160)[0], np.int64)
    assert f0[2, 2].sum() < 90                 # studio dark in the corner
    assert f0.reshape(-1, 3).sum(axis=1).max() > 300   # the lit plate reads bright


def test_webp_twin_encodes():
    data = coin_webp(_art(), n_frames=2, px=80)
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
