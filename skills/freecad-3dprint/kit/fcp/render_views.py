"""Headless orthographic renders. Run with:  FreeCADCmd.exe fcp\\render_views.py

Writes, per part, out/views/<part>_<view>.png and a contact sheet
out/views/<part>_sheet.png. Views are in PRINT orientation (Z up = away from
the bed). Overhangs steeper than print.max_overhang_deg are tinted red, so the
"bottom" view doubles as a support map.

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
BASE = np.array([0.55, 0.68, 0.85])
OVH = np.array([0.90, 0.25, 0.20])


def _unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def camera(eye, up_hint):
    e = _unit(eye)
    f = -e
    r = _unit(np.cross(f, up_hint))
    u = np.cross(r, f)
    return e, r, u


def subdivide(tri, flags, max_edge, max_tris=250000):
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
        flags = np.concatenate([flags[~big], np.tile(flags[big], 4)])
    return tri, flags


def render_view(ax, tri, flags, eye, up_hint, title=""):
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
    col = np.where(flags[vis][:, None], OVH, BASE)
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


def render_part(name, points, facets, overhang, bbox, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    tri = np.asarray(points, float)[np.asarray(facets, int)]
    flags = np.zeros(len(tri), bool) if overhang is None else np.asarray(overhang, bool)
    tri, flags = subdivide(tri, flags, max(bbox) / 40.0)
    written = []
    dims = "bbox %.2f x %.2f x %.2f mm (print orientation)" % tuple(bbox)
    for view, (eye, up) in VIEWS.items():
        fig, ax = plt.subplots(figsize=(6, 6), dpi=130)
        render_view(ax, tri, flags, eye, up, "%s - %s\n%s" % (name, view, dims))
        p = os.path.join(outdir, "%s_%s.png" % (name, view))
        fig.savefig(p, bbox_inches="tight")
        plt.close(fig)
        written.append(p)
    fig, axes = plt.subplots(2, 3, figsize=(15, 10), dpi=110)
    for ax, (view, (eye, up)) in zip(axes.flat, VIEWS.items()):
        render_view(ax, tri, flags, eye, up, view)
    fig.suptitle("%s   %s   red = overhang" % (name, dims), fontsize=11)
    p = os.path.join(outdir, "%s_sheet.png" % name)
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    written.insert(0, p)
    return written


def main():
    import Part
    from cadlib import load_params, mesh_from_shape, out_dir, print_oriented, read_json, write_json
    from check_print import facet_arrays, overhang_mask

    P = load_params()
    pr = P.get("print", {})
    result = {"ok": False, "images": []}
    try:
        status = read_json("build_status.json")
        if not status or not status.get("ok"):
            raise RuntimeError("build_status.json missing or build failed; run build.py first")
        for rec in status["parts"]:
            s = print_oriented(Part.read(rec["step"]), P)
            mesh = mesh_from_shape(s, P, linear=0.05, angular_deg=12)
            pts, facets = mesh.Topology
            points = np.array([[p.x, p.y, p.z] for p in pts])
            facets = np.array(facets, dtype=int)
            cent, nrm, _ = facet_arrays(points, facets)
            ovh = overhang_mask(nrm, cent, pr.get("max_overhang_deg", 45),
                                float(points[:, 2].min()), pr.get("layer_height", 0.2))
            bb = s.BoundBox
            result["images"] += render_part(rec["name"], points, facets, ovh,
                                            (bb.XLength, bb.YLength, bb.ZLength),
                                            os.path.join(out_dir(), "views"))
        result["ok"] = True
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc()
    write_json("render_status.json", result)
    print("RENDER", "OK" if result["ok"] else "FAILED")
    for p in result["images"]:
        print("  " + p)
    if "error" in result:
        print(result["error"])


if not os.environ.get("FCP_NO_MAIN"):
    main()
