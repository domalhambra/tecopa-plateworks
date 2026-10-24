# tests/test_orderproof.py
# The proof files Prepare writes and the studio's Save to order writes again: the proof,
# the soft proof on the roll's paper, and the client's JPG and one-page PDF. The plate is
# the synthetic Lassen mirror; the fixture is order_with_plate in tests/conftest.py.
import json
import os
import re

import pytest
from PIL import Image

from app import icc, orderproof, orderspec, panels, papers, proofpdf
from app.order import read_state, write_state

DPI = 12


@pytest.fixture
def order(order_with_plate):
    return order_with_plate


@pytest.fixture
def paper_dir(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    (d / papers.enabled_paper().profile).write_bytes(icc.srgb_profile())
    return d


def _pdf_pages(path) -> list:
    """The MediaBox (w, h) in points of each page: Pillow cannot open a PDF, and no PDF
    reader is a dependency."""
    data = open(path, "rb").read()
    assert data.startswith(b"%PDF-")
    pages = []
    for obj in re.findall(rb"\d+ 0 obj<<(.*?)>>endobj", data, re.S):
        if re.search(rb"/Type\s*/Page\b(?!s)", obj):
            w, h = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)", obj).groups()
            pages.append((float(w), float(h)))
    return pages


def _write(order, **kw):
    st = read_state(order)
    spec = orderspec.order_spec(order, st)
    return spec, orderproof.write_proofs(order, spec, orderspec.plate_dir(st), dpi=DPI, **kw)


def test_proofs_are_written_and_marked(order, paper_dir):
    spec, r = _write(order, profile_dirs=(str(paper_dir),))
    stem = orderspec.file_stem(order.title)
    for f in ("work/proof.png", "work/softproof.png",
              f"out/proof/{stem}-proof.jpg", f"out/proof/{stem}-proof.pdf"):
        assert os.path.isfile(os.path.join(order.dir, f)), f
    assert r["hash"] == orderspec.spec_hash(spec)
    assert len(r["files"]) == 4
    paper = papers.enabled_paper()
    assert r["soft_proof"] == f"{paper.profile}, {paper.intent}" and r["soft_proof_why"] is None
    png = Image.open(os.path.join(order.dir, "work/proof.png"))
    assert png.size == (round(11 * DPI), round(17 * DPI))
    assert png.info["icc_profile"] == icc.srgb_profile()
    jpg = Image.open(os.path.join(order.dir, f"out/proof/{stem}-proof.jpg"))
    assert jpg.size == png.size and jpg.info["icc_profile"] == icc.srgb_profile()


def test_the_proof_is_marked_proof(order, paper_dir):
    # the watermark changes pixels: a render without it differs from the file
    from app import render
    st = read_state(order)
    spec, _ = _write(order, profile_dirs=(str(paper_dir),))
    path = orderspec.plate_dir(st)
    cfg = json.load(open(os.path.join(path, "region.json")))
    bare = render.rasterize(spec, dpi=DPI, region_dir=path, cfg=cfg)
    marked = Image.open(os.path.join(order.dir, "work/proof.png")).convert("RGB")
    assert marked.tobytes() != bare.convert("RGB").tobytes()


def test_no_profile_skips_the_soft_proof_and_says_why(order, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _, r = _write(order, profile_dirs=(str(empty),))
    assert r["soft_proof"] is None and "not installed" in r["soft_proof_why"]
    assert papers.enabled_paper().profile in r["soft_proof_why"]
    assert not os.path.exists(os.path.join(order.dir, "work/softproof.png"))
    assert not any(f.endswith("softproof.png") for f in r["files"])
    assert len(r["files"]) == 3


def test_a_stale_soft_proof_is_removed_when_the_profile_is_gone(order, paper_dir, tmp_path):
    _write(order, profile_dirs=(str(paper_dir),))
    soft = os.path.join(order.dir, "work/softproof.png")
    assert os.path.isfile(soft)
    empty = tmp_path / "empty"
    empty.mkdir()
    _write(order, profile_dirs=(str(empty),))
    assert not os.path.exists(soft)


def test_the_files_are_the_same_bytes_for_the_same_spec(order, paper_dir):
    _write(order, profile_dirs=(str(paper_dir),))
    first = open(os.path.join(order.dir, "work/proof.png"), "rb").read()
    _write(order, profile_dirs=(str(paper_dir),))
    assert open(os.path.join(order.dir, "work/proof.png"), "rb").read() == first


def test_a_set_proof_shows_the_gaps_in_wall_tone(order, paper_dir):
    """Two panels of 17 x 22 in at a 2 in gap: a 36 x 22 in hung sheet. The synthetic
    plate (62 km wide, 10 m cells) cannot hold a three-panel frame (55 x 22 in needs
    82 km at the zoom cap), so this is the largest set it can hold."""
    st = read_state(order)
    w_in, h_in = panels.sheet_sizes(2, 2.0)[1]
    assert (w_in, h_in) == (36.0, 22.0)
    cx = (664030.0 + 726030.0) / 2
    cy = (4447820.0 + 4525010.0) / 2
    half_w = 27000.0                                  # 36 in -> 54 km, 5 m/px at 300 dpi
    half_h = half_w * h_in / w_in
    st.update(print_in=[w_in, h_in], panels=2, gap=2.0,
              frame=[cx - half_w, cy - half_h, cx + half_w, cy + half_h])
    write_state(order, st)
    spec, r = _write(order, profile_dirs=(str(paper_dir),))
    img = Image.open(os.path.join(order.dir, "work/proof.png")).convert("RGB")
    gap = panels.gap_rects_px(spec, DPI)[0]
    assert gap[2] > gap[0]
    assert img.getpixel(((gap[0] + gap[2]) // 2, h_in * DPI // 2)) == panels.WALL_TONE
    assert img.getpixel((gap[0] // 2, 10)) != panels.WALL_TONE


def test_the_pdf_is_one_page(order, paper_dir):
    _write(order, profile_dirs=(str(paper_dir),))
    stem = orderspec.file_stem(order.title)
    pages = _pdf_pages(os.path.join(order.dir, f"out/proof/{stem}-proof.pdf"))
    assert len(pages) == 1 and pages[0][0] < pages[0][1]       # an 11 x 17 map: portrait


def test_the_client_lines_are_word_for_word(order):
    lines = orderproof.client_lines(orderspec.order_spec(order, read_state(order)))
    assert lines == [
        "Proof of your Tecopa Plateworks map, 11 × 17 in.",
        "Reply to approve it, or ask for your one round of changes. "
        "Nothing prints before you approve."]


def test_proofpdf_landscape_for_a_wide_map_and_no_temp_file_left(tmp_path):
    path = str(tmp_path / "sub" / "p.pdf")
    proofpdf.write(path, Image.new("RGB", (300, 100), "white"), "Wide", ["one", "two"])
    (w, h), = _pdf_pages(path)
    assert (round(w), round(h)) == (792, 612)                  # Letter, landscape
    proofpdf.write(path, Image.new("RGB", (100, 300), "white"), "Tall", ["one"])
    (w, h), = _pdf_pages(path)
    assert (round(w), round(h)) == (612, 792)
    assert os.listdir(os.path.dirname(path)) == ["p.pdf"]


def test_proofpdf_keeps_everything_inside_the_margins():
    img = Image.new("RGB", (300, 100), "white")
    lay = proofpdf.layout(img, "A very long title " * 20, ["a long line of words " * 30])
    (pw, ph), margin = lay["page"], round(proofpdf.pp.MARGIN_IN * proofpdf.pp.PAGE_DPI)
    x, y, w, h = lay["map"]
    assert x >= margin and y >= margin and x + w <= pw - margin
    last = lay["body"][-1][1]
    assert y + h <= lay["body"][0][1] and last <= ph - margin
