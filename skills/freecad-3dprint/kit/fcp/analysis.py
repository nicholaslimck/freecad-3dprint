"""Mesh analysis shared by the checks and the renders.

Pure numpy: no FreeCAD imports. Support classification takes an injected
`contains(points) -> bool array` callable, so it can be tested without FreeCAD.

Terminology (all in print orientation, Z up):
  down face   a facet whose normal points down
  region      connected group of horizontal down faces (shares mesh edges)
  anchor      a boundary edge of a region with material just outside and just
              below it: a wall the face hangs from
  supported   material directly below the face, within support_gap
  bridge      horizontal down face anchored on two opposing sides
  cantilever  anchored on one side only
  unsupported anchored nowhere, nothing below
"""
import math

import numpy as np


def design_hash(params):
    """Hash of the design-relevant params.

    Triage records (checks.accept) and the manual preview record are excluded:
    accepting a warning or recording a slicer check must not make outputs stale.
    """
    import copy
    import hashlib
    import json

    p = copy.deepcopy(params)
    (p.get("print") or {}).pop("preview", None)
    (p.get("checks") or {}).pop("accept", None)
    blob = json.dumps(p, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- facets
def facet_arrays(points, facets):
    """points: (N,3), facets: (M,3) int -> centroids, unit normals, areas."""
    pts = np.asarray(points, dtype=float)
    tri = pts[np.asarray(facets, dtype=int)]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(cross, axis=1)
    safe = np.where(norm > 0, norm, 1.0)
    return tri.mean(axis=1), cross / safe[:, None], norm / 2.0


def overhang_mask(normals, centroids, max_overhang_deg, zmin, layer_h):
    """Facets facing down more steeply than allowed, excluding the bed layers.

    Overhang angle is measured from vertical: a 45 deg limit flags faces whose
    outward normal points down by more than sin(45 deg).

    The first two layers are not flagged: an elephant-foot chamfer lives there,
    and the bed (or squish) supports it. Deeper than that is a real overhang.
    """
    limit = math.sin(math.radians(max_overhang_deg))
    down = -normals[:, 2]
    off_bed = centroids[:, 2] > zmin + 2.0 * layer_h
    return (down > limit + 1e-6) & off_bed


def flat_down_mask(normals, centroids, zmin, layer_h):
    """Horizontal downward faces above the bed layers: bridges or need support."""
    return (-normals[:, 2] > 0.995) & (centroids[:, 2] > zmin + 2.0 * layer_h)


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


# ---------------------------------------------------------------- regions
def connected_facets(facets, mask):
    """Group the masked facets that share an edge. Returns a list of facet-index arrays."""
    sel = np.flatnonzero(mask)
    parent = list(range(len(sel)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    seen = {}
    for local, f in enumerate(sel):
        a, b, c = (int(x) for x in facets[f])
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            if key in seen:
                union(local, seen[key])
            else:
                seen[key] = local
    groups = {}
    for local in range(len(sel)):
        groups.setdefault(find(local), []).append(int(sel[local]))
    return [np.array(g, dtype=int) for g in groups.values()]


def _boundary_edges(facets, fac_idx):
    """Edges of the region used by exactly one of its facets (outer or non-down neighbours)."""
    counts = {}
    for f in fac_idx:
        a, b, c = (int(x) for x in facets[f])
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            counts[key] = counts.get(key, 0) + 1
    return [k for k, n in counts.items() if n == 1]


def _hull(points_xy):
    """Convex hull (monotone chain), counter-clockwise. Fewer than 3 points stay degenerate."""
    pts = sorted(set((round(float(p[0]), 6), round(float(p[1]), 6)) for p in points_xy))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _inside_hull(point_xy, hull, margin):
    """True if point is inside the (convex, CCW) hull with at least `margin` to spare."""
    if len(hull) < 3:
        return False
    p = np.asarray(point_xy, float)
    for i in range(len(hull)):
        a = np.asarray(hull[i], float)
        b = np.asarray(hull[(i + 1) % len(hull)], float)
        e = b - a
        ln = float(np.linalg.norm(e))
        if ln < 1e-9:
            continue
        left = np.array([-e[1], e[0]]) / ln
        if float(np.dot(p - a, left)) < margin:
            return False
    return True


def _anchors(points, edges, center, contains, out_offset=0.25, below=0.3,
             per_edge=4, max_probes=160):
    """Probe just outside each boundary edge, slightly below the face.

    Material there means the face hangs off a wall at that edge. A free end
    has air there, which is what separates a cantilever from a bridge. Each
    edge is sampled along its length: CAD exports often mesh a whole edge as
    one triangle side, and a single midpoint would lose the span.
    """
    probes = []
    c = np.asarray(center[:2], float)
    for u, v in edges:
        p0, p1 = np.asarray(points[u], float), np.asarray(points[v], float)
        d = p1 - p0
        nxy = np.array([-d[1], d[0]], float)
        ln = float(np.linalg.norm(nxy))
        if ln < 1e-9:
            continue
        nxy /= ln
        for i in range(per_edge):
            mid = p0 + d * ((i + 0.5) / per_edge)
            n = nxy if float(np.dot(mid[:2] - c, nxy)) >= 0 else -nxy
            probes.append([mid[0] + n[0] * out_offset, mid[1] + n[1] * out_offset, mid[2] - below])
    if not probes:
        return [], 0
    if len(probes) > max_probes:
        idx = np.linspace(0, len(probes) - 1, max_probes).astype(int)
        probes = [probes[i] for i in idx]
    inside = np.asarray(contains(np.asarray(probes, float)), bool)
    anchors = [{"at_mm": [round(float(x), 2) for x in probed[:3]]}
               for probed, ok in zip(probes, inside) if ok]
    return anchors, len(probes)


def classify_regions(points, facets, areas, mask, contains, support_gap=0.6, bed_z=0.0,
                     layer_h=0.2):
    """Classify each connected group of masked (down) facets.

    Returns dicts with area_mm2, center_mm, bbox_mm, span_mm, kind,
    support_fraction, anchors_mm, facet indices. Heuristic: states its own
    limits, never claims a bridge without anchors that enclose the centroid.
    """
    out = []
    pts = np.asarray(points, float)
    for fac_idx in connected_facets(facets, mask):
        tri = pts[np.asarray(facets, dtype=int)[fac_idx]]
        a = np.asarray(areas, float)[fac_idx]
        total = float(a.sum())
        if total <= 0:
            continue
        center = (tri.mean(axis=1) * a[:, None]).sum(axis=0) / total
        flat = tri.reshape(-1, 3)
        lo, hi = flat.min(axis=0), flat.max(axis=0)

        # span: longest footprint dimension. The classification itself comes from
        # where the anchors are, not from this number.
        span = float(max(hi[0] - lo[0], hi[1] - lo[1]))

        edges = _boundary_edges(facets, fac_idx)
        anchors, n_probe = _anchors(pts, edges, center, contains)

        probe = tri.mean(axis=1) - np.array([0.0, 0.0, support_gap])
        below = np.asarray(contains(probe), bool)
        bed = center[2] - support_gap <= bed_z + layer_h
        support_fraction = float(a[below].sum() / total)
        if bed:
            support_fraction = 1.0

        margin = float(min(0.5, max(0.05, 0.05 * min(hi[0] - lo[0], hi[1] - lo[1]))))
        hull = _hull([an["at_mm"][:2] for an in anchors])
        enclosed = _inside_hull(center[:2], hull, margin)

        if support_fraction >= 0.95:
            kind = "supported"
        elif not anchors:
            kind = "unsupported"
        elif enclosed:
            kind = "bridge"
        else:
            kind = "cantilever"

        out.append({
            "kind": kind,
            "area_mm2": round(total, 2),
            "center_mm": [round(float(x), 1) for x in center],
            "bbox_mm": [[round(float(x), 2) for x in lo], [round(float(x), 2) for x in hi]],
            "span_mm": round(span, 2),
            "anchors_mm": [an["at_mm"] for an in anchors][:12],
            "anchor_count": len(anchors),
            "enclosed": bool(enclosed),
            "support_fraction": round(support_fraction, 3),
            "probes": n_probe,
            "facets": fac_idx,
        })
    out.sort(key=lambda r: -r["area_mm2"])
    return out
