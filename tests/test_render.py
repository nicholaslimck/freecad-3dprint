"""Renderer regression tests. Part A is pure pytest; Part B needs freecadcmd."""
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "freecad-3dprint", "kit", "fcp")
sys.path.insert(0, KIT)
os.environ.setdefault("FCP_NO_MAIN", "1")


def test_feature_scale_makes_a_04_mm_gap_eight_pixels():
    import render_lines as rl
    part = np.array([[0.0, 0.0], [6.0, 4.0]])          # a 6 x 4 mm coupon face
    ppm = rl.px_per_mm(part, rl.VIEW_PX, rl.FEATURE_MIN_PX_PER_MM)
    assert 0.4 * ppm >= 8.0


def test_whole_part_scale_is_about_130_dpi():
    import render_lines as rl
    part = np.array([[0.0, 0.0], [136.8, 137.25]])
    ppm = rl.px_per_mm(part, rl.VIEW_PX, rl.WHOLE_PART_PX_PER_MM)
    assert ppm == pytest.approx(rl.WHOLE_PART_PX_PER_MM)     # 5.12 px/mm beats 700/137 = 5.11
    w, h = rl.png_size(part, ppm)
    # 137 mm * 5.12 px/mm, plus 4% padding on each side
    assert 700 <= w <= 780 and 700 <= h <= 780


def test_stroke_grows_with_zoom_and_never_goes_below_the_floor():
    import render_lines as rl
    # whole part at ~700 px: the floor
    assert rl.stroke_px(137.0, 700) == pytest.approx(rl.STROKE_PX)
    # a feature panel is much larger in px: the line thickens, it does not vanish
    big = rl.stroke_px(6.0, 2740)
    assert big > rl.STROKE_PX
    assert big < 6.0                      # and does not become a blob either
    # round trip through the mm conversion the SVG uses
    for w_mm, w_px in ((26.0, 700), (4.0, 80), (6.0, 2740)):
        px = rl.stroke_px(w_mm, w_px)
        assert rl.stroke_for(w_mm, w_px) * w_px / w_mm == pytest.approx(px, rel=1e-6)


def test_a_two_pixel_stroke_on_a_2740_px_canvas_is_not_hairline():
    """The bug this exists to prevent: pinning px instead of scaling with zoom."""
    import render_lines as rl
    case_px = 137.0 * rl.WHOLE_PART_PX_PER_MM        # ~701 px, today's panel
    feature_px = 6.0 * rl.FEATURE_MIN_PX_PER_MM      # 120 px minimum for a coupon
    big_px = 137.0 * rl.FEATURE_MIN_PX_PER_MM        # a large part at feature zoom
    assert rl.stroke_px(137.0, case_px) == pytest.approx(rl.STROKE_PX, abs=0.01)
    assert rl.stroke_px(137.0, big_px) > 1.5 * rl.STROKE_PX   # zoomed in, thicker
    assert rl.stroke_px(6.0, feature_px) >= rl.STROKE_PX      # small part, still visible


def test_viewport_pads_by_four_percent_of_the_part_span():
    import render_lines as rl
    edges = np.array([[10.0, 10.0], [40.0, 20.0]])
    part = np.array([[0.0, 0.0], [100.0, 50.0]])
    x0, y0, w, h, pad = rl.viewport(edges, part)
    assert pad == pytest.approx(4.0)
    assert (x0, y0) == pytest.approx((-4.0, -4.0))
    assert (w, h) == pytest.approx((108.0, 58.0))


def test_drawing_captions_and_sizes_are_present():
    import re
    import render_lines as rl
    lines = [np.array([[0.0, 0.0], [10.0, 0.0]]), np.array([[0.0, 0.0], [0.0, 5.0]])]
    part = np.array([[0.0, 0.0], [10.0, 5.0]])
    svg = rl.drawing(lines, part, caption=["part_v3 - front", "bbox 10.00 x 5.00 x 2.00 mm",
                                          "scale 20.00 px/mm"], minimum_px_per_mm=20.0)
    assert svg.lstrip().startswith("<svg") and svg.rstrip().endswith("</svg>")
    for word in ("part_v3 - front", "bbox 10.00 x 5.00 x 2.00 mm", "scale 20.00 px/mm"):
        assert word in svg
    assert 'stroke-width="' in svg
    w, h = rl.svg_size(svg)
    assert w == int(re.search(r'width="(\d+)"', svg).group(1)) and w >= 10 * 20


def test_drawing_with_no_edges_still_produces_a_captioned_svg():
    import render_lines as rl
    svg = rl.drawing([], np.array([[0.0, 0.0], [1.0, 1.0]]), caption=["empty view"])
    assert "empty view" in svg and "</svg>" in svg


def test_drawing_panel_is_sized_by_the_part_not_fitted_to_view_px():
    """A 10 mm part at 20 px/mm is ~216 px, not 756: the scale floor is authoritative."""
    import render_lines as rl
    part = np.array([[0.0, 0.0], [10.0, 5.0]])
    svg = rl.drawing([np.array([[0.0, 0.0], [10.0, 0.0]])], part, caption=["x"],
                     minimum_px_per_mm=20.0)
    w, h = rl.svg_size(svg)
    assert w < 300, "panel was fitted to VIEW_PX instead of the part's own scale"
    assert w >= int(10.0 * 20.0)


def test_drawing_caption_fits_inside_the_canvas():
    import re
    import render_lines as rl
    part = np.array([[0.0, 0.0], [10.0, 5.0]])
    svg = rl.drawing([], part, caption=["a", "b", "c"], minimum_px_per_mm=20.0)
    last_y = max(float(y) for y in re.findall(r'y="([\d.]+)" font', svg))
    _, h = rl.svg_size(svg)
    assert last_y < h - 2, "the last caption line is clipped by the canvas"


def _tri_cube():
    """A 10 mm cube as points/facets with outward normals (reuses test_fcp._box)."""
    import test_fcp
    return test_fcp._box((0, 0, 0), (10, 10, 10))


def test_render_part_records_an_engine_per_image(tmp_path):
    pytest.importorskip("matplotlib", reason="raster engine needs FreeCAD's bundled matplotlib")
    import render_views as rv
    pts, faces = _tri_cube()
    bbox = (10.0, 10.0, 10.0)
    recs = rv.render_part("t", pts, faces, None, bbox, str(tmp_path / "views"))
    assert recs and all(set(r) == {"path", "view", "engine"} for r in recs)
    assert all(r["engine"] == "raster" for r in recs)
    assert {r["view"] for r in recs} == set(rv.VIEWS)
