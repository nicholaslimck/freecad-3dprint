"""Tests for the pure-Python parts of the kit (no FreeCAD needed).

Run:  pip install numpy pytest && pytest
"""
import math
import os
import sys
import time

import numpy as np

os.environ["FCP_NO_MAIN"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "freecad-3dprint", "kit", "fcp"))

from check_print import facet_arrays, flat_down_mask, overhang_mask  # noqa: E402
from slice import fill, fresh_gcode  # noqa: E402


def _tilted(deg_from_vertical, z):
    """Downward-facing facet at height z, tilted deg_from_vertical (0 = vertical wall, 90 = flat roof)."""
    t = math.radians(deg_from_vertical)
    # Edge along X; third vertex goes up along +Z and out along -Y; (b-a)x(c-a) points down and -Y.
    a, b = (0.0, 0.0, z), (1.0, 0.0, z)
    c = (0.0, -math.sin(t), z + math.cos(t))
    return [a, b, c]


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
