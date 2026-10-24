# tests/test_softproof.py
"""The sRGB profile and the soft proof live in app/icc.py (plan decision P8): order
modules import them without importing app.main, which starts queues and caches."""
import os
import subprocess
import sys

import pytest
from PIL import Image

from app import icc

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_main_still_embeds_the_same_profile_bytes():
    from app import main
    assert main.SRGB_PROFILE == icc.srgb_profile()


def test_icc_does_not_import_main():
    code = "import sys; import app.icc; sys.exit(1 if 'app.main' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], cwd=REPO).returncode == 0


def test_a_missing_profile_is_none(tmp_path):
    assert icc.find_profile("Nope.icc", dirs=(str(tmp_path),)) is None


def test_a_profile_is_found_in_the_first_directory_that_holds_it(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    (b / "P.icc").write_bytes(icc.srgb_profile())
    assert icc.find_profile("P.icc", dirs=(str(a), str(b))) == str(b / "P.icc")


def test_find_profile_expands_the_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Profiles").mkdir()
    (tmp_path / "Profiles" / "P.icc").write_bytes(icc.srgb_profile())
    assert icc.find_profile("P.icc", dirs=("~/Profiles",)) == str(tmp_path / "Profiles" / "P.icc")


def test_soft_proof_runs_and_keeps_the_size(tmp_path):
    paper = tmp_path / "paper.icc"
    paper.write_bytes(icc.srgb_profile())          # sRGB stands in for a paper in CI
    img = Image.new("RGB", (40, 30), (200, 120, 60))
    out = icc.soft_proof(img, str(paper), "perceptual")
    assert out.size == (40, 30) and out.mode == "RGB"


@pytest.mark.parametrize("intent", ["perceptual", "relative"])
def test_soft_proof_takes_each_intent(tmp_path, intent):
    paper = tmp_path / "paper.icc"
    paper.write_bytes(icc.srgb_profile())
    out = icc.soft_proof(Image.new("RGB", (8, 8), (10, 200, 90)), str(paper), intent)
    assert out.size == (8, 8)


def test_soft_proof_refuses_an_unknown_intent(tmp_path):
    paper = tmp_path / "paper.icc"
    paper.write_bytes(icc.srgb_profile())
    with pytest.raises(ValueError):
        icc.soft_proof(Image.new("RGB", (8, 8)), str(paper), "saturation")
