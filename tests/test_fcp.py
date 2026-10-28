"""Tests for the pure-Python parts of the kit (no FreeCAD needed).

Run:  pip install numpy pytest && pytest
"""
import math
import json
import os
import sys
import time

import numpy as np

os.environ["FCP_NO_MAIN"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "freecad-3dprint", "kit", "fcp"))

from analysis import (  # noqa: E402
    classify_regions,
    design_hash,
    facet_arrays,
    flat_down_mask,
    overhang_mask,
)
from slice import fill, fresh_gcode  # noqa: E402
from gate import evaluate  # noqa: E402
from release import release  # noqa: E402
from status import status  # noqa: E402
from doctor import nested_workspace  # noqa: E402


def _tilted(deg_from_vertical, z):
    """Downward-facing facet at height z, tilted deg_from_vertical (0 = vertical wall, 90 = flat roof)."""
    t = math.radians(deg_from_vertical)
    # Edge along X; third vertex goes up along +Z and out along -Y; (b-a)x(c-a) points down and -Y.
    a, b = (0.0, 0.0, z), (1.0, 0.0, z)
    c = (0.0, -math.sin(t), z + math.cos(t))
    return [a, b, c]


def test_first_two_layers_count_as_bed():
    # an elephant-foot chamfer lives in the first 0.4 mm and must not be flagged
    tris = [_tilted(90, 0.2), _tilted(90, 0.3), _tilted(90, 0.5)]
    points = np.array([p for t in tris for p in t])
    facets = np.arange(len(points)).reshape(-1, 3)
    cent, nrm, _ = facet_arrays(points, facets)
    assert flat_down_mask(nrm, cent, 0.0, 0.2).tolist() == [False, False, True]
    assert overhang_mask(nrm, cent, 45, 0.0, 0.2).tolist() == [False, False, True]


def test_design_hash_ignores_triage_and_preview():
    from analysis import design_hash

    base = {"geometry": {"a": 1}, "print": {"preview": {"done": False}},
            "checks": {"accept": []}}
    accepted = json.loads(json.dumps(base))
    accepted["print"]["preview"] = {"done": True}
    accepted["checks"]["accept"] = [{"code": "flat_bridge", "reason": "x", "evidence": "y"}]
    assert design_hash(base) == design_hash(accepted)

    changed = json.loads(json.dumps(base))
    changed["geometry"]["a"] = 2
    assert design_hash(base) != design_hash(changed)


def test_overhang_and_bridge_masks():
    tris = [
        _tilted(45, 5.0),  # chamfer at the limit: prints fine
        _tilted(60, 5.0),  # steeper than the limit: overhang
        _tilted(90, 5.0),  # flat roof: bridge
        _tilted(90, 0.0),  # bed face: excluded
    ]
    points = np.array([p for t in tris for p in t])
    facets = np.arange(len(points)).reshape(-1, 3)
    cent, nrm, _ = facet_arrays(points, facets)
    assert (nrm[:, 2] < 0).all()  # all face down, as intended

    ovh = overhang_mask(nrm, cent, 45, 0.0, 0.2)
    flat = flat_down_mask(nrm, cent, 0.0, 0.2)
    assert ovh.tolist() == [False, True, True, False]
    assert flat.tolist() == [False, False, True, False]


# ---------------------------------------------------------------- support classification
_BOX_FACES = ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
              (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
              (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7))


def _box(lo, hi):
    """Closed axis-aligned box as (points, facets), outward normals."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    pts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
           (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    return pts, list(_BOX_FACES)


def _union(*boxes):
    pts, faces = [], []
    for lo, hi in boxes:
        p, f = _box(lo, hi)
        off = len(pts)
        pts += p
        faces += [(a + off, b + off, c + off) for a, b, c in f]
    return np.array(pts, float), np.array(faces, int)


def _contains(boxes):
    """Point-in-solid for a union of axis-aligned boxes."""
    def fn(points):
        out = []
        for p in np.asarray(points, float):
            out.append(any(all(lo[i] - 1e-9 <= p[i] <= hi[i] + 1e-9 for i in range(3))
                           for lo, hi in boxes))
        return np.array(out, bool)
    return fn


def _classify(points, facets, boxes, support_gap=0.6):
    cent, nrm, area = facet_arrays(points, facets)
    mask = flat_down_mask(nrm, cent, 0.0, 0.2)
    return classify_regions(points, facets, area, mask, _contains(boxes),
                            support_gap=support_gap, bed_z=0.0)


def test_shelf_attached_at_one_end_is_a_cantilever():
    # wall + 12 x 4 x 0.8 shelf whose underside is at z=10, rooted on the wall
    boxes = [((0, -6, 0), (2, 6, 20)), ((2, -6, 10), (6, 6, 10.8))]
    pts, faces = _union(*boxes)
    regions = _classify(pts, faces, boxes)
    assert len(regions) == 1
    r = regions[0]
    assert r["kind"] == "cantilever", r
    assert abs(r["area_mm2"] - 12 * 4) < 0.1
    assert abs(r["span_mm"] - 12) < 0.1, r["span_mm"]
    assert r["anchor_count"] > 0
    assert r["support_fraction"] == 0.0


def test_strap_between_two_towers_is_a_bridge():
    boxes = [((0, -6, 0), (2, 6, 20)), ((10, -6, 0), (12, 6, 20)),
             ((2, -4, 10), (10, 4, 10.8))]
    pts, faces = _union(*boxes)
    regions = _classify(pts, faces, boxes)
    assert len(regions) == 1
    assert regions[0]["kind"] == "bridge", regions[0]


def test_floating_plate_is_unsupported():
    boxes = [((0, 0, 10), (10, 4, 10.8))]
    pts, faces = _union(*boxes)
    regions = _classify(pts, faces, boxes)
    assert len(regions) == 1
    assert regions[0]["kind"] == "unsupported", regions[0]


def test_plate_over_material_is_supported_not_a_bridge():
    boxes = [((0, 0, 0), (10, 4, 9.6)), ((0, 0, 10), (10, 4, 10.8))]
    pts, faces = _union(*boxes)
    regions = _classify(pts, faces, boxes, support_gap=0.6)
    assert len(regions) == 1
    assert regions[0]["kind"] == "supported", regions[0]


def test_separate_shelves_are_separate_regions():
    boxes = [((0, -6, 0), (2, 6, 20)), ((2, -6, 10), (6, 6, 10.8)),
             ((20, -6, 0), (22, 6, 20)), ((22, -6, 10), (26, 6, 10.8))]
    pts, faces = _union(*boxes)
    regions = _classify(pts, faces, boxes)
    assert len(regions) == 2
    assert all(r["kind"] == "cantilever" for r in regions)


# ---------------------------------------------------------------- slicer helpers
def test_fresh_gcode_ignores_previous_runs(tmp_path):
    stale = tmp_path / "old.gcode"
    stale.write_text("old")
    os.utime(stale, (time.time() - 3600,) * 2)
    t0 = time.time() - 1
    expected = str(tmp_path / "part.gcode")

    assert fresh_gcode(expected, str(tmp_path), t0) is None

    new = tmp_path / "part_plate_1.gcode"
    new.write_text("new")
    assert fresh_gcode(expected, str(tmp_path), t0) == str(new)

    (tmp_path / "part.gcode").write_text("exact")
    assert fresh_gcode(expected, str(tmp_path), t0) == expected


def test_fill_keeps_literal_braces():
    subs = {"model": "m.3mf", "gcode": "g", "outdir": "o", "config": "c.ini"}
    assert fill("{model}", subs) == "m.3mf"
    assert fill('{"a":1}', subs) == '{"a":1}'


# ---------------------------------------------------------------- print gate
def _gate_params(accept=None, preview=None):
    return {
        "checks": {"accept": accept or []},
        "print": {"supports_allowed": False, "preview": preview or {}},
    }


CANTILEVER_WARNING = {
    "code": "flat_cantilever",
    "text": "shelf anchored on one side",
    "region": {"center_mm": [5.0, 0.0, 10.0], "span_mm": 20.0, "area_mm2": 80.0},
}
PART_WIDE_WARNING = {"code": "small_bed_contact", "text": "small bed contact"}
PREVIEW = {"done": True, "supports_off": True, "by": "user", "date": "2026-10-28",
           "evidence": "layers 40-52 checked"}
ACCEPT = {"code": "flat_cantilever", "region_center_mm": [5.0, 0.0, 10.0],
          "reason": "intentional", "evidence": "coupon printed clean"}


def _gate_fixture(accept=None, preview=None, warnings=None):
    P = _gate_params(accept, preview)
    digest = design_hash(P)
    report = {"pass": True, "design_hash": digest,
              "parts": [{"name": "part", "errors": [], "info": [],
                         "warnings": [CANTILEVER_WARNING] if warnings is None else warnings}]}
    render = {"ok": True, "images": ["sheet.png"], "warnings": [], "design_hash": digest}
    manifest = {"sources": {"design": digest},
                "parts": [{"name": "part", "sha256": {"3mf": "abc"}}]}
    return P, report, render, manifest


def test_gate_refuses_untriaged_warning_and_missing_preview():
    P, report, render, manifest = _gate_fixture()
    result = evaluate(P, report, render, manifest, None)
    assert not result["printable"]
    assert result["untriaged"] and result["untriaged"][0]["code"] == "flat_cantilever"
    assert any("not print-verified" in r for r in result["reasons"])


def test_gate_accepts_warning_with_evidence_and_manual_preview():
    P, report, render, manifest = _gate_fixture([ACCEPT], PREVIEW)
    result = evaluate(P, report, render, manifest, None)
    assert result["printable"], result["reasons"]
    assert result["checks"]["preview"]["mode"] == "manual"


def test_gate_acceptance_needs_evidence():
    partial = dict(ACCEPT)
    partial.pop("evidence")
    P, report, render, manifest = _gate_fixture([partial], PREVIEW)
    result = evaluate(P, report, render, manifest, None)
    assert not result["printable"]
    assert "evidence" in result["untriaged"][0].get("accept_error", "")


def test_gate_blanket_acceptance_does_not_cover_a_region():
    blanket = {k: v for k, v in ACCEPT.items() if k != "region_center_mm"}
    P, report, render, manifest = _gate_fixture([blanket], PREVIEW)
    assert not evaluate(P, report, render, manifest, None)["printable"]

    # ...but it does cover a warning with no region of its own
    P, report, render, manifest = _gate_fixture(
        [{"code": "small_bed_contact", "reason": "brim", "evidence": "brim in profile"}],
        PREVIEW, warnings=[PART_WIDE_WARNING])
    assert evaluate(P, report, render, manifest, None)["printable"]


def test_gate_manual_preview_needs_by_date_and_evidence():
    P, report, render, manifest = _gate_fixture([ACCEPT], {"done": True, "supports_off": True})
    result = evaluate(P, report, render, manifest, None)
    assert not result["printable"]
    assert any("print-verified" in r for r in result["reasons"])


def test_gate_rejects_stale_report_and_render():
    P, report, render, manifest = _gate_fixture([ACCEPT], PREVIEW)
    report["design_hash"] = "old"
    render["design_hash"] = "old"
    result = evaluate(P, report, render, manifest, None)
    assert not result["printable"]
    assert any("different build" in r for r in result["reasons"])


def test_gate_rejects_slice_of_a_different_file():
    P, report, render, manifest = _gate_fixture([], PREVIEW, warnings=[])
    sliced = {"ok": True, "design_hash": design_hash(P), "supports_allowed": False,
              "parts": [{"name": "part", "gcode": "p.gcode",
                         "model_sha256": "stale", "warnings": []}]}
    result = evaluate(P, report, render, manifest, sliced)
    assert not result["printable"]
    assert any("different file" in r for r in result["reasons"])


# ---------------------------------------------------------------- release
def _release_fixture(tmp_path, printable=True, stale=False):
    project = tmp_path / "proj"
    workspace = project / ".freecad-3dprint"
    out = workspace / ".out"
    out.mkdir(parents=True)
    params = {"name": "case", "version": 3,
              "print": {"rotate": [], "supports_allowed": False,
                        "nozzle": 0.4, "layer_height": 0.2}}
    (workspace / "params.json").write_text(json.dumps(params))
    for name in ("part.step", "part_print.3mf", "part_print.stl", "case_v3.FCStd"):
        (out / name).write_text(name)
    manifest = {"parts": [{"name": "part", "step": str(out / "part.step"),
                           "3mf": str(out / "part_print.3mf"),
                           "stl": str(out / "part_print.stl")}],
                "fcstd": str(out / "case_v3.FCStd")}
    gate = {"printable": printable,
            "design_hash": "old" if stale else design_hash(params),
            "checks": {"preview": {"mode": "slicer"}}}
    (out / "manifest.json").write_text(json.dumps(manifest))
    (out / "print_gate.json").write_text(json.dumps(gate))
    (out / "report.json").write_text(json.dumps({"pass": True, "parts": []}))
    return workspace


def test_release_copies_verified_files(tmp_path):
    workspace = _release_fixture(tmp_path)
    status = release(str(workspace))
    assert status["ok"], status["reasons"]
    dest = tmp_path / "proj" / "print" / "case_v3"
    for name in ("part_print.3mf", "part_print.stl", "part.step", "case_v3.FCStd",
                 "report.json", "print_gate.json", "README.md", "release.json"):
        assert (dest / name).exists(), name
    record = json.loads((dest / "release.json").read_text())
    params = json.loads((workspace / "params.json").read_text())
    assert record["design_hash"] == design_hash(params)


def test_release_refuses_unverified_or_stale(tmp_path):
    unverified = _release_fixture(tmp_path / "unverified", printable=False)
    assert not release(str(unverified))["ok"]
    stale = _release_fixture(tmp_path / "stale", stale=True)
    assert not release(str(stale))["ok"]


# ---------------------------------------------------------------- status / workspace layout
def _status_fixture(tmp_path):
    workspace = tmp_path / "proj" / ".freecad-3dprint"
    out = workspace / ".out"
    out.mkdir(parents=True)
    (workspace / "params.json").write_text(json.dumps({"name": "case", "version": 3,
                                                       "print": {"supports_allowed": False}}))
    return workspace, out


def test_status_without_a_build(tmp_path):
    workspace, _ = _status_fixture(tmp_path)
    result = status(str(workspace))
    assert result["stem"] == "case_v3"
    assert "no build" in result["next"]
    assert result["slice_this"] == []


def test_status_points_at_the_current_file_and_release(tmp_path):
    workspace, out = _status_fixture(tmp_path)
    model = out / "case_v3_print.3mf"
    model.write_text("3mf")
    manifest = {"parts": [{"name": "case", "slice_this": str(model), "step": "case.step"}]}
    gate = {"printable": True, "reasons": [], "checks": {"preview": {"mode": "slicer"}}}
    (out / "manifest.json").write_text(json.dumps(manifest))
    (out / "print_gate.json").write_text(json.dumps(gate))
    release_dir = tmp_path / "proj" / "print" / "case_v3"
    release_dir.mkdir(parents=True)

    result = status(str(workspace))
    assert result["gate"]["printable"] and result["gate"]["verified"] == "slicer"
    assert result["slice_this"] == [str(model)]
    assert result["release_dir"] == str(release_dir)
    assert "released" in result["next"]


def test_status_reports_a_blocked_gate(tmp_path):
    workspace, out = _status_fixture(tmp_path)
    (out / "manifest.json").write_text(json.dumps({"parts": []}))
    (out / "print_gate.json").write_text(json.dumps(
        {"printable": False, "reasons": ["not print-verified"]}))
    result = status(str(workspace))
    assert "blocked" in result["next"]
    assert "not print-verified" in result["next"]


def test_nested_workspace_is_detected(tmp_path):
    outer = tmp_path / ".freecad-3dprint"
    inner = outer / "part" / ".freecad-3dprint"
    inner.mkdir(parents=True)
    assert nested_workspace(str(inner)) == str(outer)
    normal = tmp_path / "proj" / ".freecad-3dprint"
    normal.mkdir(parents=True)
    assert nested_workspace(str(normal)) == ""
