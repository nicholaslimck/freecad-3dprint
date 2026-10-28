"""Parametric build script. Run with:  FreeCADCmd.exe build.py   (or fcp\\run.ps1)

Edit ONLY the feature functions and build(). All numbers come from params.json;
do not hard-code dimensions here. Each feature is its own function so a change
to one feature never requires regenerating the others.

Coupons are cut from the real part (params.coupon), not modelled separately:
that keeps the real wall, lip, groove and print orientation, and stops a feature
fix from existing in only one copy.

The example part is a mounting plate with four counterbored M3 holes. Replace it.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("FCP_PROJECT") or os.getcwd(), "fcp"))
from cadlib import *  # noqa: E402,F401,F403

P = load_params()
WARN = []  # non-fatal problems (e.g. a fillet that OCC refused); reported in build_status.json


# ---------------------------------------------------------------- features
def base_plate(g):
    return rounded_box(g["length"], g["width"], g["thickness"], g["corner_radius"], center_xy=True)


def mounting_holes(s, g):
    dx = g["length"] / 2.0 - g["hole_inset"]
    dy = g["width"] / 2.0 - g["hole_inset"]
    top = g["thickness"]
    for x in (-dx, dx):
        for y in (-dy, dy):
            s = counterbore(s, g["hole_d"], None, g["cb_d"], g["cb_depth"], at=(x, y, top))
    return s


def top_edge_round(s, g):
    # Outer perimeter of the top face only (OuterWire skips the counterbore circles).
    top = largest_face_at_z(s, g["thickness"])
    return safe_fillet(s, g.get("top_fillet", 0), top.OuterWire.Edges, WARN)


# ---------------------------------------------------------------- assembly
def build(params):
    """Build every part from `params`. Called again with overrides for coupon variants."""
    g = params["geometry"]
    s = base_plate(g)
    s = mounting_holes(s, g)
    s = top_edge_round(s, g)
    s = chamfer_bed_edges(s, params["print"].get("elephant_foot_chamfer", 0), params, WARN)
    return s.removeSplitter()
    # Multi-part projects: return {"lid": lid_shape, "base": base_shape}


# ---------------------------------------------------------------- main
def main():
    status = {"ok": False, "warnings": WARN}
    try:
        result = build(P)
        parts = dict(result) if isinstance(result, dict) else {P.get("name", "part"): result}
        parts = add_coupons(parts, P, build, WARN)
        for name, sh in parts.items():
            if not sh.isValid():
                raise RuntimeError("shape '%s' is invalid after build" % name)
        records, fcstd = export_all(parts, P)
        status.update(ok=True, parts=records, fcstd=fcstd)
        sheet = write_coupon_sheet(P, records)
        if sheet:
            status["coupon_sheet"] = sheet
    except Exception:  # noqa: BLE001
        status["error"] = traceback.format_exc()
    write_json("build_status.json", status)
    print("BUILD", "OK" if status["ok"] else "FAILED")
    if not status["ok"]:
        print(status["error"])
    for w in WARN:
        print("  warning: " + w)


main()
