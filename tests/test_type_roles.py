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


def _capture_curved(monkeypatch):
    """Spy on _curved_plan: {text: tracking} for every curved label laid."""
    captured = {}
    orig = render._curved_plan
    def spy(d, poly, text, font, tracking, halo, min_len):
        captured[text] = tracking
        return orig(d, poly, text, font, tracking, halo, min_len)
    monkeypatch.setattr(render, "_curved_plan", spy)
    return captured


def _render_labelled(spec_kw=None):
    from tests.test_labels import _spec, _labels_for
    spec = _spec(labels=True, **(spec_kw or {}))
    return render.rasterize(spec, dpi=96, region_dir="regions/lassen_ca",
                            hydro={"lakes": [], "rivers": []}, labels=_labels_for(spec))


def test_area_labels_default_to_tracked_caps(monkeypatch):
    # The free chain has no small caps, so the area register is ALL CAPS, letterspaced.
    # This pins today's behaviour: no binding, no change.
    monkeypatch.delenv("TECOPA_FONT_AREA_CASE", raising=False)
    captured = _capture_curved(monkeypatch)
    _render_labelled()
    assert "TEST RANGE" in captured
    assert captured["TEST RANGE"] > 0, "the caps register must stay letterspaced"


def test_a_small_caps_binding_keeps_case_and_tracking(monkeypatch):
    # Advocate draws small caps from LOWERCASE positions (no smcp feature), so an
    # operator binding it must also switch the register to mixed case -- and the
    # letterspacing belongs to the register, not to the casing, so it must survive.
    monkeypatch.setenv("TECOPA_FONT_AREA_CASE", "mixed")
    captured = _capture_curved(monkeypatch)
    _render_labelled()
    assert "Test Range" in captured, "mixed register must keep the name's own case"
    assert captured["Test Range"] > 0, "tracking must not ride out with the casing"


def test_an_unknown_case_value_is_refused(monkeypatch):
    monkeypatch.setenv("TECOPA_FONT_AREA_CASE", "smallcaps")
    with pytest.raises(ValueError):
        _render_labelled()


def test_size_scale_is_unity_when_unbound(monkeypatch):
    for var in list(__import__("os").environ):
        if var.startswith("TECOPA_FONT"):
            monkeypatch.delenv(var, raising=False)
    for role in render.TYPE_ROLES:
        assert render._size_scale(role, caps=False) == 1.0
        assert render._size_scale(role, caps=True) == 1.0


def test_size_scale_matches_register_metrics(monkeypatch):
    # A bound face is sized so its register metric (x-height for text, cap-height for
    # the caps register) matches the default chain's at the same nominal size. Faked
    # metrics, because this host has one usable font.
    class Fake:
        def __init__(self, h): self.h = h
        def getbbox(self, ch): return (0, 0, 60, self.h)
    monkeypatch.setenv("TECOPA_FONT_POINT", "SomeFace.otf")
    monkeypatch.setattr(render, "_font_at",
                        lambda face, size: Fake(54 if face else 48))   # taller x-height
    assert render._size_scale("point", caps=False) == pytest.approx(48 / 54)


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
