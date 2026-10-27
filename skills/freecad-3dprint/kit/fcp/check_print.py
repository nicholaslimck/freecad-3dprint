"""Printability checks. Run with:  FreeCADCmd.exe fcp\\check_print.py   (after build.py)

Reads out/build_status.json, checks every part in PRINT orientation and writes
out/report.json:
  {"pass": bool, "parts": [{"name", "errors": [], "warnings": [], "info": [], "metrics": {}}]}
errors   = must fix before printing
warnings = probably fix, or justify in the hand-off summary
info     = things a human should know (e.g. horizontal holes that may sag)
"""
import math
import os
import sys
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- pure numpy analysis
def facet_arrays(points, facets):
    """points: (N,3), facets: (M,3) int -> centroids, unit normals, areas."""
    pts = np.asarray(points, dtype=float)
    tri = pts[np.asarray(facets, dtype=int)]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(cross, axis=1)
    safe = np.where(norm > 0, norm, 1.0)
    return tri.mean(axis=1), cross / safe[:, None], norm / 2.0


def overhang_mask(normals, centroids, max_overhang_deg, zmin, layer_h):
    """Facets facing down more steeply than allowed, excluding the bed layer.

    Overhang angle is measured from vertical: a 45 deg limit flags faces whose
    outward normal points down by more than sin(45 deg).
    """
    limit = math.sin(math.radians(max_overhang_deg))
    down = -normals[:, 2]
    off_bed = centroids[:, 2] > zmin + layer_h * 0.5
    return (down > limit + 1e-6) & off_bed


def flat_down_mask(normals, centroids, zmin, layer_h):
    """Horizontal downward faces above the bed: bridges or needs support."""
    return (-normals[:, 2] > 0.995) & (centroids[:, 2] > zmin + layer_h * 0.5)


def bed_contact_area(normals, centroids, areas, zmin):
    m = (-normals[:, 2] > 0.995) & (np.abs(centroids[:, 2] - zmin) < 1e-3)
    return float(areas[m].sum())


def group_regions(centroids, areas, mask, cell=5.0, top=8):
    """Bin flagged facets into cell-sized cubes; return the largest regions."""
    if not mask.any():
        return []
    keys = np.floor(centroids[mask] / cell).astype(int)
    a = areas[mask]
    c = centroids[mask]
    regions = {}
    for k, ar, ce in zip(map(tuple, keys), a, c):
        r = regions.setdefault(k, [0.0, np.zeros(3)])
        r[0] += ar
        r[1] += ce * ar
    out = [{"area_mm2": round(float(v[0]), 2), "center_mm": [round(float(x), 1) for x in (v[1] / v[0])]}
           for v in regions.values() if v[0] > 0]
    out.sort(key=lambda r: -r["area_mm2"])
    return out[:top]


# ---------------------------------------------------------------- FreeCAD checks
def wall_thickness_scan(shape, min_wall, per_face=4, max_samples=800):
    """Ray-march inward from sample points on every face.

    Returns (min_found_or_None, list of thin spots). Thickness is only resolved
    up to 3*min_wall; thicker walls are reported as ">= limit".
    """
    from FreeCAD import Vector as V

    limit = max(min_wall * 3.0, 1.0)
    step = min_wall / 8.0
    samples = []
    for f in shape.Faces:
        try:
            u0, u1, v0, v1 = f.ParameterRange
        except Exception:  # noqa: BLE001
            continue
        if not all(map(math.isfinite, (u0, u1, v0, v1))):
            continue
        for i in range(per_face):
            for j in range(per_face):
                u = u0 + (u1 - u0) * (i + 0.5) / per_face
                v = v0 + (v1 - v0) * (j + 0.5) / per_face
                try:
                    if not f.isPartOfDomain(u, v):
                        continue
                    samples.append((f.valueAt(u, v), f.normalAt(u, v)))
                except Exception:  # noqa: BLE001
                    continue
    if len(samples) > max_samples:
        idx = np.linspace(0, len(samples) - 1, max_samples).astype(int)
        samples = [samples[i] for i in idx]

    def inside(p):
        return shape.isInside(p, 1e-5, False)

    thin, found = [], None
    for p, n in samples:
        n = V(n.x, n.y, n.z)
        if inside(p - n * 0.02):
            d = n * -1.0
        elif inside(p + n * 0.02):
            d = n
        else:
            continue
        t = 0.02
        while t < limit and inside(p + d * (t + step)):
            t += step
        if t >= limit:
            continue
        lo, hi = t, t + step  # bisect the exit point
        for _ in range(6):
            mid = (lo + hi) / 2.0
            if inside(p + d * mid):
                lo = mid
            else:
                hi = mid
        th = round(lo, 3)
        found = th if found is None else min(found, th)
        if th < min_wall:
            thin.append({"thickness_mm": th, "at_mm": [round(p.x, 2), round(p.y, 2), round(p.z, 2)]})
    thin.sort(key=lambda r: r["thickness_mm"])
    return found, thin[:10], len(samples)


def horizontal_holes(shape, min_d):
    """Cylindrical HOLES (not bosses) whose axis is horizontal in print orientation."""
    import Part
    from FreeCAD import Vector as V

    hits = []
    for f in shape.Faces:
        s = f.Surface
        if not isinstance(s, Part.Cylinder):
            continue
        ax = s.Axis
        if abs(ax.z) > 0.1 or 2 * s.Radius < min_d:
            continue
        com = f.CenterOfMass
        rel = com - s.Center
        on_axis = s.Center + V(ax.x, ax.y, ax.z) * rel.dot(ax)
        if shape.isInside(on_axis, 1e-4, True):
            continue  # axis point is in material -> convex boss, not a hole
        if not shape.isInside(on_axis + V(0, 0, s.Radius * 1.1), 1e-4, True):
            continue  # open above the arc -> teardrop roof or concave fillet, nothing to sag
        hits.append({"d_mm": round(2 * s.Radius, 2),
                     "at_mm": [round(on_axis.x, 1), round(on_axis.y, 1), round(on_axis.z, 1)]})
    return hits


def check_part(rec, P):
    import Part
    from cadlib import mesh_from_shape, print_oriented

    pr = P.get("print", {})
    layer = pr.get("layer_height", 0.2)
    nozzle = pr.get("nozzle", 0.4)
    min_wall = pr.get("min_wall", 2 * nozzle)
    res = {"name": rec["name"], "errors": [], "warnings": [], "info": [], "metrics": {}}
    E, W, I, M = res["errors"], res["warnings"], res["info"], res["metrics"]

    design = Part.read(rec["step"])
    # --- topology
    if not design.isValid():
        E.append("B-rep shape is invalid (shape.isValid() is False)")
    n_solids = len(design.Solids)
    M["solids"] = n_solids
    if n_solids != 1:
        E.append("expected exactly 1 solid, found %d (unfused bodies or a cut that split the part)" % n_solids)
    M["volume_mm3"] = round(design.Volume, 2)

    # --- expected design dimensions
    chk = P.get("checks", {})
    if chk.get("bbox_mm"):
        bb = design.BoundBox
        got = [bb.XLength, bb.YLength, bb.ZLength]
        tol = chk.get("bbox_tol", 0.05)
        M["design_bbox_mm"] = [round(x, 3) for x in got]
        if any(abs(g - e) > tol for g, e in zip(got, chk["bbox_mm"])):
            E.append("design bbox %s != expected %s (tol %s)" % (M["design_bbox_mm"], chk["bbox_mm"], tol))

    # --- print orientation
    s = print_oriented(design, P)
    bb = s.BoundBox
    M["print_bbox_mm"] = [round(bb.XLength, 2), round(bb.YLength, 2), round(bb.ZLength, 2)]
    vol = pr.get("build_volume")
    if vol and any(d > v for d, v in zip(sorted(M["print_bbox_mm"][:2]) + [bb.ZLength],
                                         sorted(vol[:2]) + [vol[2]])):
        E.append("part %s does not fit build volume %s" % (M["print_bbox_mm"], vol))

    # --- mesh health
    mesh = mesh_from_shape(s, P, linear=max(0.02, layer / 10), angular_deg=10)
    for attr, bad, msg in (("isSolid", False, "mesh is not watertight"),
                           ("hasNonManifolds", True, "mesh has non-manifold edges"),
                           ("hasSelfIntersections", True, "mesh self-intersects")):
        fn = getattr(mesh, attr, None)
        if fn is None:
            continue
        try:
            if bool(fn()) == bad:
                E.append(msg)
        except Exception as exc:  # noqa: BLE001
            I.append("mesh check %s unavailable: %s" % (attr, exc))

    pts, facets = mesh.Topology
    points = np.array([[p.x, p.y, p.z] for p in pts])
    cent, nrm, area = facet_arrays(points, facets)
    zmin = float(points[:, 2].min())

    # --- overhangs / bridges / bed contact
    ovh = overhang_mask(nrm, cent, pr.get("max_overhang_deg", 45), zmin, layer)
    flat = flat_down_mask(nrm, cent, zmin, layer)
    steep = ovh & ~flat
    M["overhang_area_mm2"] = round(float(area[steep].sum()), 2)
    M["flat_downward_area_mm2"] = round(float(area[flat].sum()), 2)
    if M["overhang_area_mm2"] > 1.0:
        msg = "%.1f mm2 of overhang steeper than %s deg; regions: %s" % (
            M["overhang_area_mm2"], pr.get("max_overhang_deg", 45), group_regions(cent, area, steep))
        (W if pr.get("supports_allowed") else E).append(msg)
    if M["flat_downward_area_mm2"] > 1.0:
        W.append("%.1f mm2 of flat downward faces above the bed (bridges, or need support); regions: %s" % (
            M["flat_downward_area_mm2"], group_regions(cent, area, flat)))

    contact = bed_contact_area(nrm, cent, area, zmin)
    M["bed_contact_mm2"] = round(contact, 2)
    footprint = bb.XLength * bb.YLength
    if contact < 25 or (footprint > 0 and contact / footprint < 0.1):
        W.append("small bed contact (%.1f mm2); consider re-orienting or a brim" % contact)
    min_xy = min(bb.XLength, bb.YLength)
    if min_xy > 0 and bb.ZLength / min_xy > 4:
        W.append("tall and thin (height/width %.1f); may wobble or snap at layer lines" % (bb.ZLength / min_xy))

    # --- wall thickness
    found, thin, n = wall_thickness_scan(s, min_wall)
    M["min_wall_found_mm"] = found
    M["wall_samples"] = n
    if thin:
        E.append("walls thinner than %s mm: %s" % (min_wall, thin))

    # --- horizontal holes
    holes = horizontal_holes(s, pr.get("teardrop_above_d", 5))
    if holes:
        I.append("horizontal holes >= %s mm will sag at the top; use teardrop_hole or ream: %s"
                 % (pr.get("teardrop_above_d", 5), holes))
    return res


def main():
    from cadlib import load_params, read_json, write_json

    P = load_params()
    report = {"pass": False, "parts": []}
    try:
        status = read_json("build_status.json")
        if not status or not status.get("ok"):
            raise RuntimeError("build_status.json missing or build failed; run build.py first")
        for rec in status["parts"]:
            report["parts"].append(check_part(rec, P))
        report["pass"] = all(not p["errors"] for p in report["parts"])
    except Exception:  # noqa: BLE001
        report["error"] = traceback.format_exc()
    write_json("report.json", report)
    print("CHECK", "PASS" if report["pass"] else "FAIL")
    for p in report["parts"]:
        for k in ("errors", "warnings", "info"):
            for m in p[k]:
                print("  [%s] %s: %s" % (k[:-1].upper() if k != "info" else "INFO", p["name"], m))
    if "error" in report:
        print(report["error"])


if not os.environ.get("FCP_NO_MAIN"):
    main()
