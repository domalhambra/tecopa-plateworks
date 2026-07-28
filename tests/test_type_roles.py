# tests/test_type_roles.py
"""The per-role font seam: naming a role must not move a pixel until a role is bound."""
import pytest

from app import render


def test_an_unbound_role_is_the_very_same_font_object(monkeypatch):
    # Identity, not .path: the last-resort load_default() has a BytesIO path, and this
    # host may hold only Georgia (CI only DejaVu) -- the one portable assertion is that
    # an unbound role and the plain call share a cache entry, and therefore an FT_Face.
    monkeypatch.delenv("TECOPA_FONT", raising=False)
    plain = render._font(24)
    for role in render.TYPE_ROLES:
        assert render._font(24, role) is plain, f"unbound role {role!r} must share the chain"


def test_an_unknown_role_is_refused():
    with pytest.raises(ValueError):
        render._font(24, "cartouche")      # not in TYPE_ROLES -- a typo, not a feature


def test_a_bound_role_wins_over_the_sheet_wide_face(monkeypatch):
    # Bind to names with different RESOLUTIONS, not different installed files: this host
    # has Georgia but no DejaVu, CI the reverse, so the portable pair is "a real name"
    # vs "a name that falls through to the default chain".
    monkeypatch.delenv("TECOPA_FONT", raising=False)
    monkeypatch.setenv("TECOPA_FONT_POINT", "Georgia.ttf")
    monkeypatch.setenv("TECOPA_FONT_AREA", "ThisFaceDoesNotExist.ttf")   # -> fallback chain
    assert render._font(24, "point") is not render._font(24, "area")


def test_rebinding_a_role_is_not_served_from_the_cache(monkeypatch):
    monkeypatch.setenv("TECOPA_FONT_POINT", "Georgia.ttf")
    first = render._font(24, "point")
    monkeypatch.setenv("TECOPA_FONT_POINT", "AlsoNotAFace.ttf")
    assert render._font(24, "point") is not first


def test_each_label_kind_asks_for_its_own_role(monkeypatch):
    # Routing, not pixels: a summit must request "point", a range "area", the
    # cartouche "title". _spec(labels=True) puts a range and a summit in crop and
    # sets title_text, so all three are reachable. (water is not -- _labels_for
    # passes no lakes -- and that is fine; hydro routing shares the same code path.)
    from tests.test_labels import _spec, _labels_for
    asked = []
    real = render._font
    monkeypatch.setattr(render, "_font",
                        lambda size, role="body": (asked.append(role), real(size, role))[1])
    spec = _spec(labels=True)
    render.rasterize(spec, dpi=96, region_dir="regions/lassen_ca",
                     hydro={"lakes": [], "rivers": []}, labels=_labels_for(spec))
    assert {"point", "area", "title"} <= set(asked)
