"""Headless orthographic renders. Run with:  FreeCADCmd.exe fcp\\render_views.py

Writes, per part, .out/views/<stem>_<view>.png and a contact sheet
.out/views/<stem>_sheet.png. Views are in PRINT orientation (Z up = away from
the bed). Steep overhangs are red; flat down faces classified as cantilever or
unsupported are amber, so the bottom view doubles as a support map.

params.render.features[] adds a close-up sheet and optional section per feature:
  {"name": "latch", "bbox_mm": [[x0,y0,z0],[x1,y1,z1]],
   "section": {"axis": "y", "at_mm": 12.0}}     # keeps the low side of the plane
The feature bbox is in PRINT orientation (after print.rotate), not design coordinates:
use the numbers from the sheet or from report.metrics.print_bbox_mm.

Uses numpy + matplotlib (bundled with FreeCAD on Windows). Painter's-algorithm
rendering: fine for checking shape and feature placement, not photoreal.
"""
import math
import os
import sys
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# eye direction (object -> camera), up hint
VIEWS = {
    "iso":    ((1.0, -1.0, 0.8), (0, 0, 1)),
    "front":  ((0.0, -1.0, 0.0), (0, 0, 1)),
    "right":  ((1.0, 0.0, 0.0), (0, 0, 1)),
    "top":    ((0.0, 0.0, 1.0), (0, 1, 0)),
    "back_iso": ((-1.0, 1.0, 0.8), (0, 0, 1)),
    "bottom": ((0.0, 0.0, -1.0), (0, 1, 0)),
}
FEATURE_VIEWS = {"iso": VIEWS["iso"], "front": VIEWS["front"],
                 "top": VIEWS["top"], "bottom": VIEWS["bottom"]}
COLORS = np.array([[0.55, 0.68, 0.85],   # 0 normal
                   [0.90, 0.25, 0.20],   # 1 steep overhang
                   [0.95, 0.65, 0.15]])  # 2 flat down, cantilever/unsupported


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def camera(eye, up_hint):
    e = _unit(eye)
    f = -e
    r = _unit(np.cross(f, up_hint))
    u = np.cross(r, f)
    return e, r, u


def subdivide(tri, cat, max_edge, max_tris=250000):
    """Split big triangles (4-way midpoint) so painter's-algorithm sorting stays correct."""
    for _ in range(8):
        e = np.stack([np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1),
                      np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1),
                      np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)], axis=1).max(axis=1)
        big = e > max_edge
        if not big.any() or len(tri) + 3 * big.sum() > max_tris:
            break
        t = tri[big]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        split = np.concatenate([np.stack(x, axis=1) for x in
                                ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))])
        tri = np.concatenate([tri[~big], split])
        cat = np.concatenate([cat[~big], np.tile(cat[big], 4)])
    return tri, cat


def render_view(ax, tri, cat, eye, up_hint, title=""):
    from matplotlib.collections import PolyCollection

    e, r, u = camera(eye, up_hint)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1)
    keep = ln > 0
    n[keep] /= ln[keep][:, None]
    vis = keep & (n @ e > 1e-6)
    tri_v, n_v = tri[vis], n[vis]
    xy = np.stack([tri_v @ r, tri_v @ u], axis=-1)
    depth = (tri_v @ e).mean(axis=1)
    order = np.argsort(depth)  # far first

    light = _unit(e + 0.5 * u + 0.35 * r)
    shade = 0.45 + 0.55 * np.clip(n_v @ light, 0, 1)
    span = np.ptp(depth) if len(depth) else 0.0
    if span > 0:  # depth cue: nearer is brighter, so pocket floors read differently from tops
        shade *= 0.72 + 0.28 * (depth - depth.min()) / span
    col = COLORS[np.clip(cat[vis], 0, 2)]
    col = np.clip(col * shade[:, None], 0, 1)

    pc = PolyCollection(xy[order], facecolors=col[order], edgecolors=col[order], linewidths=0.25)
    ax.add_collection(pc)
    pts = tri.reshape(-1, 3)
    all_xy = np.stack([pts @ r, pts @ u], axis=-1)
    lo, hi = all_xy.min(0), all_xy.max(0)
    pad = 0.06 * max(hi - lo)
    ax.set_xlim(lo[0] - pad, hi[0] + pad)
    ax.set_ylim(lo[1] - pad, hi[1] + pad)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=9)
    ax.tick_params(labelsize=7)
    ax.grid(True, linewidth=0.3, alpha=0.4)


def render_part(name, points, facets, cat, bbox, outdir, views=None, tag=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    views = views or VIEWS
    os.makedirs(outdir, exist_ok=True)
    tri = np.asarray(points, float)[np.asarray(facets, int)]
    cat = np.zeros(len(tri), np.int8) if cat is None else np.asarray(cat, np.int8)
    tri, cat = subdivide(tri, cat, max(bbox) / 40.0)
    written = []
    dims = "bbox %.2f x %.2f x %.2f mm (print orientation)" % tuple(bbox)
    for view, (eye, up) in views.items():
        fig, ax = plt.subplots(figsize=(6, 6), dpi=130)
        render_view(ax, tri, cat, eye, up, "%s - %s\n%s" % (name, view, dims))
        p = os.path.join(outdir, "%s%s_%s.png" % (name, tag, view))
        fig.savefig(p, bbox_inches="tight")
        plt.close(fig)
        written.append(p)
    n = len(views)
    cols = 2 if n <= 4 else 3
    rows = int(math.ceil(n / float(cols)))
    fig, axes = plt.subplots(rows, cols, figsize=(7.5 * cols, 5 * rows), dpi=110, squeeze=False)
    for ax, (view, (eye, up)) in zip(axes.flat, views.items()):
        render_view(ax, tri, cat, eye, up, view)
    for ax in list(axes.flat)[len(views):]:
        ax.axis("off")
    fig.suptitle("%s   %s   red = overhang, amber = unsupported shelf" % (name, dims), fontsize=11)
    p = os.path.join(outdir, "%s%s_sheet.png" % (name, tag))
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    written.insert(0, p)
    return written


def _check_print_module():
    """Import check_print without letting its main() run again (FCP_NO_MAIN guard)."""
    previous = os.environ.get("FCP_NO_MAIN")
    os.environ["FCP_NO_MAIN"] = "1"
    try:
        import check_print
    finally:
        if previous is None:
            os.environ.pop("FCP_NO_MAIN", None)
        else:
            os.environ["FCP_NO_MAIN"] = previous
    return check_print


def categories(shape, P, points, facets):
    """0 normal, 1 steep overhang, 2 flat down face that is a cantilever or unsupported."""
    from analysis import facet_arrays, flat_down_mask, overhang_mask

    classify_down_faces = _check_print_module().classify_down_faces

    pr = P.get("print", {})
    cent, nrm, area = facet_arrays(points, facets)
    zmin = float(points[:, 2].min())
    flat = flat_down_mask(nrm, cent, zmin, pr.get("layer_height", 0.2))
    steep = overhang_mask(nrm, cent, pr.get("max_overhang_deg", 45), zmin,
                          pr.get("layer_height", 0.2)) & ~flat
    cat = steep.astype(np.int8)
    try:
        _, regions = classify_down_faces(shape, points, facets, cent, nrm, area, zmin, P)
    except Exception:  # noqa: BLE001 - tint what we can; the report says it failed
        return cat
    for region in regions:
        if region["kind"] in ("cantilever", "unsupported"):
            cat[region["facets"]] = 2
    return cat


def feature_shape(shape, feat):
    """Clip to the feature box, then (optionally) keep the low side of a section plane."""
    from cadlib import section

    lo, hi = [list(map(float, corner)) for corner in feat["bbox_mm"]]
    clipped = section(shape, lo, hi)
    sec = feat.get("section")
    if sec:
        axis = str(sec.get("axis", "y")).lower()
        if axis not in ("x", "y", "z"):
            raise ValueError("render.features[%s].section.axis must be x, y or z" % feat.get("name"))
        at = float(sec["at_mm"])
        i = "xyz".index(axis)
        hi2 = list(hi)
        hi2[i] = min(at, hi[i])
        if hi2[i] <= lo[i]:
            raise ValueError("render.features[%s].section.at_mm is outside the feature bbox"
                             % feat.get("name"))
        clipped = section(clipped, lo, hi2)
    return clipped


def main():
    import Part
    from analysis import design_hash
    from cadlib import load_params, mesh_from_shape, out_dir, print_oriented, read_json, write_json

    P = load_params()
    result = {"ok": False, "images": [], "warnings": [], "design_hash": design_hash(P)}
    try:
        status = read_json("build_status.json")
        if not status or not status.get("ok"):
            raise RuntimeError("build_status.json missing or build failed; run build.py first")
        for rec in status["parts"]:
            stem = rec.get("stem") or rec["name"]
            s = print_oriented(Part.read(rec["step"]), P)
            mesh = mesh_from_shape(s, P, linear=0.05, angular_deg=12)
            pts, facets = mesh.Topology
            points = np.array([[p.x, p.y, p.z] for p in pts])
            facets = np.array(facets, dtype=int)
            bb = s.BoundBox
            result["images"] += render_part(
                stem, points, facets, categories(s, P, points, facets),
                (bb.XLength, bb.YLength, bb.ZLength), os.path.join(out_dir(), "views"))

            for feat in P.get("render", {}).get("features", []):
                try:
                    fs = feature_shape(s, feat)
                    fmesh = mesh_from_shape(fs, P, linear=0.02, angular_deg=8)
                    fpts, ffacets = fmesh.Topology
                    fpoints = np.array([[p.x, p.y, p.z] for p in fpts])
                    ffacets = np.array(ffacets, dtype=int)
                    fbb = fs.BoundBox
                    result["images"] += render_part(
                        stem, fpoints, ffacets, categories(fs, P, fpoints, ffacets),
                        (fbb.XLength, fbb.YLength, fbb.ZLength), os.path.join(out_dir(), "views"),
                        views=FEATURE_VIEWS, tag="_" + str(feat["name"]))
                except Exception as exc:  # noqa: BLE001 - one bad feature must not lose the sheet
                    result["warnings"].append("feature render %s failed: %s" % (feat.get("name"), exc))
        result["ok"] = True
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc()
    write_json("render_status.json", result)
    print("RENDER", "OK" if result["ok"] else "FAILED")
    for p in result["images"]:
        print("  " + p)
    for w in result["warnings"]:
        print("  ! " + w)
    if "error" in result:
        print(result["error"])


if not os.environ.get("FCP_NO_MAIN"):
    main()
