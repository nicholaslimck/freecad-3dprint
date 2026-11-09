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


def test_whole_part_raster_renders_only_the_bottom_view(tmp_path):
    pytest.importorskip("matplotlib", reason="raster engine needs FreeCAD's bundled matplotlib")
    import render_views as rv
    pts, faces = _tri_cube()
    recs = rv.render_part("t", pts, faces, None, (10.0, 10.0, 10.0), str(tmp_path),
                          views=rv.SUPPORT_VIEWS)
    views = {r["view"] for r in recs} - {"sheet"}
    assert views == {"bottom"}


def _classify_stub(shape, points, facets, cent, nrm, area, zmin, P):
    """Support-aware stub: an unsupported flat-down facet is one with nothing below it.

    Deliberately simple geometry-only logic so the test pins the renderer's
    plumbing (whole part -> coupon) rather than the real classifier's heuristics.
    """
    import analysis
    flat = analysis.flat_down_mask(nrm, cent, zmin, (P.get("print") or {}).get("layer_height", 0.2))
    pts = np.asarray(points, float)
    tri = pts[np.asarray(facets, int)]
    regions = []
    for i in np.flatnonzero(flat):
        probe = tri[i].mean(axis=0) - np.array([0.0, 0.0, 0.5])
        below = pts[pts[:, 2] < probe[2]]
        supported = bool(len(below)) and bool(
            np.any((np.abs(below[:, :2] - probe[:2]) < 3.0).all(axis=1)))
        if not supported:
            regions.append({"kind": "unsupported", "facets": np.array([i])})
    return {}, regions


def _partial_shelf():
    """A shelf whose underside is half supported (a pillar) and half over air.

    Built as disjoint boxes: `test_fcp._union` only concatenates faces, so
    overlapping boxes leave doubled and inside-out triangles.

      base plate   z 0..2
      back wall    z 2..20
      pillar       z 2..10, x 10..16   -> supports the shelf's right half
      shelf        z 10..10.8          -> underside at z=10
    """
    import test_fcp
    boxes = [((0, 0, 0), (20, 20, 2)),            # base plate (bed)
             ((0, 0, 2), (20, 2, 20)),            # back wall
             ((10, 2, 2), (16, 16, 10)),          # pillar under the shelf's right half
             ((0, 2, 10), (20, 18, 10.8))]        # the shelf
    pts, faces = test_fcp._union(*boxes)
    return np.asarray(pts, float), np.asarray(faces, int).reshape(-1, 3)


def test_floating_shelf_underside_is_amber():
    import analysis
    import render_views as rv
    pts, faces = _partial_shelf()
    cat = rv.part_categories(None, {"print": {"layer_height": 0.2}},
                             pts, faces, classify_down_faces=_classify_stub)
    cent, nrm, _ = analysis.facet_arrays(pts, faces)
    under = (-nrm[:, 2] > 0.995) & (np.abs(cent[:, 2] - 10.0) < 1e-3)
    assert under.any()
    assert (cat[under] == 2).all()
    top = (nrm[:, 2] > 0.995) & (np.abs(cent[:, 2] - 20.0) < 1e-3)
    assert top.any() and (cat[top] == 0).all()     # the wall tops stay normal


def test_clipped_feature_gets_the_whole_part_category_array():
    """A coupon's categories must come from the whole part, not from re-classifying the crop.

    This pins the plumbing: `map_categories` reproduces the whole-part array on
    the surviving facets. It does not claim the two paths differ in colour for
    this fixture - see the Task 7 ledger note: for the support map both paths
    land on the same category on every fixture we could build, because the
    category depends on material below and a mesh cut either keeps or removes it
    symmetrically. What this test does prove is that no facet loses its
    whole-part category on the way through the clip.
    """
    import analysis
    import render_views as rv
    pts, faces = _partial_shelf()
    whole = rv.part_categories(None, {"print": {"layer_height": 0.2}},
                               pts, faces, classify_down_faces=_classify_stub)
    cent, _, _ = analysis.facet_arrays(pts, faces)
    keep = cent[:, 0] < 10.0                       # half the shelf, a whole triangle wide
    fpts, remap = np.unique(faces[keep].ravel(), return_inverse=True)
    ffacets = remap.reshape(-1, 3)
    fcat = rv.map_categories(pts, faces, whole, pts[fpts], ffacets)
    fcent, fnrm, _ = analysis.facet_arrays(pts[fpts], ffacets)
    under = (-fnrm[:, 2] > 0.995) & (np.abs(fcent[:, 2] - 10.0) < 1e-3)
    assert under.any()
    # every surviving facet carries the category its source facet had
    _, _, _ = analysis.facet_arrays(pts, faces)
    src = np.array([int(np.argmin(np.linalg.norm(cent - c, axis=1))) for c in fcent])
    assert (fcat == whole[src]).all()
    assert (fcat[under] == 2).all()
