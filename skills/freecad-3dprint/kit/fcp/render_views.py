"""Support-map renders. Run with:  FreeCADCmd.exe fcp\\render_views.py

This module draws ONLY the bottom (bed-facing) support map; shape views come
from render_lines.py. Writes, per part, .out/views/<stem>_bottom.png and a
one-panel sheet .out/views/<stem>_sheet.png. Views are in PRINT orientation
(Z up = away from the bed). Steep overhangs are red; flat down faces classified
as cantilever or unsupported are amber, so the bottom view doubles as a support
map.

params.render.features[] adds a close-up support panel and optional section per
feature:
  {"name": "latch", "bbox_mm": [[x0,y0,z0],[x1,y1,z1]],
   "section": {"axis": "y", "at_mm": 12.0}}     # keeps the low side of the plane
The feature bbox is in PRINT orientation (after print.rotate), not design coordinates:
use the numbers from the sheet or from report.metrics.print_bbox_mm.

Uses numpy + matplotlib (bundled with FreeCAD on Windows). Painter's-algorithm
rendering: fine for checking shape and feature placement, not photoreal.
"""
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
# The raster engine's job is the support map. Bottom views are the only ones it
# draws: that is where the red/amber categories are the question being asked.
SUPPORT_VIEWS = {"bottom": VIEWS["bottom"]}
FEATURE_SUPPORT_VIEWS = {"bottom": VIEWS["bottom"]}
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
        written.append({"path": p, "view": view, "engine": "raster"})
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


def part_categories(shape, P, points, facets, classify_down_faces=None):
    """0 normal, 1 steep overhang, 2 flat down face that is a cantilever or unsupported.

    Classify the WHOLE part once. A clipped feature uses `map_categories` against
    these arrays rather than classifying its own cropped copy: cropping changes
    what counts as "material below", so a coupon could classify differently from
    the solid it was cut from.
    """
    from analysis import facet_arrays, flat_down_mask, overhang_mask

    if classify_down_faces is None:
        if shape is None:
            raise ValueError("part_categories needs classify_down_faces when shape is None")
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


def categories(shape, P, points, facets, classify_down_faces=None):
    """Kept for callers that want the whole-part array; see part_categories()."""
    return part_categories(shape, P, points, facets, classify_down_faces)


def map_categories(src_points, src_facets, src_cat, dst_points, dst_facets):
    """Category per destination facet, matched by centroid to the source mesh.

    Both meshes are in the same coordinate frame; a feature mesh is the part
    mesh clipped, so every destination centroid coincides with a source one.

    ponytail: O(n*m) nearest-centroid match; a KD-tree from scipy is the upgrade
    if a feature ever carries >50k facets. scipy is not a FreeCAD dependency today.
    """
    from analysis import facet_arrays

    src_cent, _, _ = facet_arrays(src_points, src_facets)
    dst_cent, _, _ = facet_arrays(dst_points, dst_facets)
    out = np.zeros(len(dst_cent), np.int8)
    if len(src_cent) == 0 or len(dst_cent) == 0:
        return out
    span = float(np.linalg.norm(np.ptp(np.asarray(src_points, float), axis=0)))
    tol = max(1e-9, 1e-3 * span)
    for i, c in enumerate(dst_cent):
        d = np.linalg.norm(src_cent - c, axis=1)
        j = int(d.argmin())
        if d[j] <= tol:
            out[i] = src_cat[j]
    return out


def feature_shape(shape, feat, apply_section=True):
    """Clip to the feature box, then (unless apply_section is False) keep the low side of the section plane."""
    from cadlib import section

    lo, hi = [list(map(float, corner)) for corner in feat["bbox_mm"]]
    clipped = section(shape, lo, hi)
    sec = feat.get("section") if apply_section else None
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


def _clear_stale_views(outdir):
    """Remove images written by the old single-engine layout.

    Before the two-engine split, render_views wrote `<stem>_<view>.png` and
    `<stem>_sheet.png`. Those now sit next to `<stem>_<view>_lines.png`,
    `<stem>_support_bottom.png` and the new sheet, and a reader cannot tell
    which are current. Everything that is not a current-layout name is removed;
    only `.png` files are touched.
    """
    if not os.path.isdir(outdir):
        return
    for name in os.listdir(outdir):
        stem, ext = os.path.splitext(name)
        if ext.lower() != ".png":
            continue
        if _is_current_view_image(stem):
            continue
        try:
            os.remove(os.path.join(outdir, name))
        except OSError:  # noqa: BLE001 - a locked file is not worth failing the render
            pass


def _is_current_view_image(stem):
    """True for a name the current renderer writes: <stem>_<view>_lines or <stem>_support_bottom.

    ponytail: a name-suffix allowlist. If the output naming changes again, update
    this one function; a manifest of written files would be the upgrade, but the
    renderer would then have to read its own previous manifest to know what to
    delete, which is more moving parts than this is worth today.
    """
    for suffix in ("_lines", "_support_bottom"):
        if stem.endswith(suffix):
            return True
    return stem.endswith("_sheet")       # the current sheet reuses the old name


def main():
    import Part
    from analysis import design_hash
    import render_lines
    from cadlib import load_params, mesh_from_shape, out_dir, print_oriented, read_json, write_json

    P = load_params()
    _clear_stale_views(os.path.join(out_dir(), "views"))
    result = {"ok": False, "images": [], "warnings": [], "timings": [],
              "design_hash": design_hash(P)}
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
            bbox = (bb.XLength, bb.YLength, bb.ZLength)
            outdir = os.path.join(out_dir(), "views")
            part_cats = part_categories(s, P, points, facets)   # once per part, reused below

            # shape: TechDraw line art
            shape_records, shape_warnings, timings = render_lines.render_part(
                s, stem, bbox, outdir)
            result["warnings"] += shape_warnings
            result["timings"] += timings

            # support: the flat raster classification, bottom view only
            support_records = render_part(
                stem, points, facets, part_cats, bbox, outdir,
                views=SUPPORT_VIEWS, tag="_support")

            ordered = shape_records + support_records
            sheet_path = os.path.join(outdir, "%s_sheet.png" % stem)
            render_lines.contact_sheet(
                [r["path"] for r in ordered], sheet_path,
                "%s   bbox %.2f x %.2f x %.2f mm   red = overhang, amber = unsupported shelf"
                % ((stem,) + bbox),
                render_lines.ENGINE_FOOTER)
            result["images"] += [{"path": sheet_path, "view": "sheet", "engine": "mixed"}]
            result["images"] += ordered
            result["engine_footer"] = render_lines.ENGINE_FOOTER

            for feat in P.get("render", {}).get("features", []):
                try:
                    ftag = "_" + str(feat["name"])
                    sec = feat.get("section")
                    # the feature as-is, and (when it declares one) the sectioned cut
                    variants = [("", None)]
                    if sec:
                        variants.append(("_section",
                                         "section: %s=%.2f mm" % (sec["axis"], float(sec["at_mm"]))))
                    for vsuffix, sec_text in variants:
                        fs = feature_shape(s, feat, apply_section=bool(vsuffix))
                        fbb = fs.BoundBox
                        fbox = (fbb.XLength, fbb.YLength, fbb.ZLength)
                        vtag = ftag + vsuffix
                        # shape: line art at the feature's OWN span (BC5), never the part's
                        fshape, fwarn, ftime = render_lines.render_part(
                            fs, stem, fbox, outdir, views=render_lines.FEATURE_SHAPE_VIEWS,
                            tag=vtag, section_text=sec_text, feature=True)
                        result["warnings"] += fwarn
                        result["timings"] += ftime

                        # support: whole-part categories mapped onto the coupon
                        fmesh = mesh_from_shape(fs, P, linear=0.02, angular_deg=8)
                        fpts, ffacets = fmesh.Topology
                        fpoints = np.array([[p.x, p.y, p.z] for p in fpts])
                        ffacets = np.array(ffacets, dtype=int)
                        fcats = map_categories(points, facets, part_cats, fpoints, ffacets)
                        fsup = render_part(
                            stem, fpoints, ffacets, fcats, fbox, outdir,
                            views=FEATURE_SUPPORT_VIEWS, tag=vtag + "_support")
                        result["images"] += fshape + fsup
                except Exception as exc:  # noqa: BLE001 - one bad feature must not lose the sheet
                    result["warnings"].append("feature render %s failed: %s" % (feat.get("name"), exc))
        result["ok"] = True
    except Exception:  # noqa: BLE001
        result["error"] = traceback.format_exc()
    write_json("render_status.json", result)
    print("RENDER", "OK" if result["ok"] else "FAILED")
    for rec in result["images"]:
        print("  " + rec["path"])
    for w in result["warnings"]:
        print("  ! " + w)
    if "error" in result:
        print(result["error"])


from cli import run

run(main, module_name=__name__)
