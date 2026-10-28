"""Printability checks. Run with:  FreeCADCmd.exe fcp\\check_print.py   (after build.py)

Reads .out/build_status.json, checks every part in PRINT orientation and writes
.out/report.json:
  {"pass": bool, "parts": [{"name", "errors": [], "warnings": [], "info": [], "metrics": {}}],
   "relations": [...], "coupon": [...]}
Each finding is {"code", "text", ...detail}. codes are stable names so params.json
checks.accept can triage a warning by code and region.
errors   = must fix before printing
warnings = fix, or accept in params.checks.accept with evidence (the print gate
           refuses to call the part printable until every warning is triaged)
info     = things a human should know (e.g. a declared, proven bridge)
"""
import math
import os
import sys
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis import (  # noqa: E402
    bed_contact_area,
    classify_regions,
    facet_arrays,
    flat_down_mask,
    group_regions,
    overhang_mask,
)


# ---------------------------------------------------------------- findings
def finding(code, text, **extra):
    out = {"code": code, "text": text}
    out.update(extra)
    return out


def _brief(components):
    return "; ".join("%.1f mm3 at %s" % (c["volume_mm3"], c["bbox_mm"]) for c in components[:6])


def _region_ref(r):
    return {"area_mm2": r["area_mm2"], "center_mm": r["center_mm"],
            "bbox_mm": r["bbox_mm"], "span_mm": r["span_mm"],
            "support_fraction": r["support_fraction"], "anchor_count": r["anchor_count"]}


# ---------------------------------------------------------------- FreeCAD probes
def make_contains(shape):
    """Containment probe for the analysis module, one FreeCAD call per point."""
    from FreeCAD import Vector as V

    def contains(points):
        pts = np.asarray(points, float)
        out = np.zeros(len(pts), bool)
        for i, p in enumerate(pts):
            out[i] = bool(shape.isInside(V(float(p[0]), float(p[1]), float(p[2])), 1e-6, False))
        return out
    return contains


def classify_down_faces(shape, points, facets, cent, nrm, area, zmin, P):
    """Flat-down regions classified as bridge / cantilever / unsupported / supported."""
    pr = P.get("print", {})
    layer = pr.get("layer_height", 0.2)
    mask = flat_down_mask(nrm, cent, zmin, layer)
    regions = classify_regions(points, facets, area, mask, make_contains(shape),
                               support_gap=pr.get("support_gap_mm", 0.6),
                               bed_z=zmin, layer_h=layer)
    return mask, regions


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


# ---------------------------------------------------------------- expectations
def _expected(value, name, default=1):
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return value


def _bbox_spec(chk, name, multi):
    """Expected bbox for this part, plus an ambiguity warning for list form with many parts."""
    spec = chk.get("bbox_mm")
    if not spec:
        return None, None
    if isinstance(spec, dict):
        return spec.get(name), None
    if multi:
        return spec, ("checks.bbox_mm is a single box applied to every part; "
                      "use {\"<part name>\": [x, y, z]}")
    return spec, None


def _declared(P, region):
    """The checks.accept entry, if any, that covers this region."""
    for item in P.get("checks", {}).get("accept", []):
        c = item.get("region_center_mm")
        if not c:
            continue
        tol = max(5.0, 0.25 * float(region["span_mm"]))
        if float(np.linalg.norm(np.asarray(c, float) - np.asarray(region["center_mm"], float))) <= tol:
            return item
    return None


def _region_findings(P, regions):
    """Turn classified down faces into findings.

    A declared bridge that the geometry shows as a cantilever is an error: that is
    the false justification this check exists for. Accepting the correct code for
    the observed kind (flat_cantilever, flat_unsupported) leaves a warning so the
    print gate still sees the acceptance record.
    """
    out = []
    for r in regions:
        ref = _region_ref(r)
        decl = _declared(P, r)
        where = "center %s, bbox %s" % (r["center_mm"], r["bbox_mm"])
        if r["kind"] == "bridge":
            text = ("%.1f mm2 flat downward face (%s) spans %.1f mm and is anchored at both ends "
                    "(anchors %d, support below %.0f%%)"
                    % (r["area_mm2"], where, r["span_mm"], r["anchor_count"],
                       100 * r["support_fraction"]))
            if decl and decl.get("code") == "flat_bridge":
                out.append(("info", finding("flat_bridge", text + "; accepted: " + str(decl.get("reason", "")),
                                            region=ref)))
            else:
                out.append(("warning", finding(
                    "flat_bridge", text + "; if the bridge is intentional, accept it in checks.accept "
                    "with code flat_bridge and evidence (span, test print)", region=ref)))
        elif r["kind"] == "cantilever":
            text = ("%.1f mm2 cantilevered shelf (%s): anchored on one side only, span %.1f mm, "
                    "anchors %d, material below %.0f%%"
                    % (r["area_mm2"], where, r["span_mm"], r["anchor_count"],
                       100 * r["support_fraction"]))
            if decl and decl.get("code") in ("flat_bridge", "overhang_steep"):
                out.append(("error", finding(
                    "declared_bridge_is_cantilever",
                    text + "; it is declared as %s, but the geometry has one-sided support. "
                    "Fix the geometry; the bridge claim is not supported." % decl.get("code"), region=ref)))
            else:
                out.append(("warning", finding(
                    "flat_cantilever", text + "; it will droop or need support. Redesign, or accept "
                    "with checks.accept code flat_cantilever and test the coupon", region=ref)))
        elif r["kind"] == "unsupported":
            if decl and decl.get("code") in ("flat_bridge", "flat_cantilever"):
                out.append(("error", finding(
                    "declared_bridge_is_cantilever",
                    "%.1f mm2 horizontal down face (%s) is declared as %s, but it has no support "
                    "below and no anchor. Fix the geometry or the declaration."
                    % (r["area_mm2"], where, decl.get("code")), region=ref)))
            else:
                out.append(("warning", finding(
                    "flat_unsupported", "%.1f mm2 horizontal down face (%s) has no support below and no "
                    "anchor; print it with supports or change the design" % (r["area_mm2"], where),
                    region=ref)))
    return out


def check_part(rec, P, designs, multi):
    from FreeCAD import Vector as V
    from cadlib import mesh_from_shape, print_oriented

    pr = P.get("print", {})
    layer = pr.get("layer_height", 0.2)
    nozzle = pr.get("nozzle", 0.4)
    min_wall = pr.get("min_wall", 2 * nozzle)
    chk = P.get("checks", {})
    res = {"name": rec["name"], "errors": [], "warnings": [], "info": [], "metrics": {}}
    E, W, I, M = res["errors"], res["warnings"], res["info"], res["metrics"]

    design = designs[rec["name"]]
    # --- topology and components
    if not design.isValid():
        E.append(finding("invalid_brep", "B-rep shape is invalid (shape.isValid() is False)"))
    comps = []
    for sol in design.Solids:
        bb = sol.BoundBox
        comps.append({
            "volume_mm3": round(sol.Volume, 2),
            "bbox_mm": [[round(bb.XMin, 2), round(bb.YMin, 2), round(bb.ZMin, 2)],
                        [round(bb.XMax, 2), round(bb.YMax, 2), round(bb.ZMax, 2)]],
        })
    comps.sort(key=lambda c: -c["volume_mm3"])
    n_solids = len(comps)
    M["solids"] = n_solids
    M["components"] = comps
    M["volume_mm3"] = round(design.Volume, 2)
    want = int(_expected(chk.get("expected_solids"), rec["name"], 1))
    if n_solids != want:
        E.append(finding("components_unexpected",
                         "expected %d solid(s), found %d; components: %s. A floating body means a "
                         "feature is not attached to its parent." % (want, n_solids, _brief(comps)),
                         components=comps))
    n_shells = len(design.Shells)
    if n_shells != n_solids:
        W.append(finding("open_shell",
                         "shape has %d shell(s) for %d solid(s); an open shell will not print as a "
                         "closed part" % (n_shells, n_solids)))

    # --- expected design dimensions
    exp_bbox, ambiguous = _bbox_spec(chk, rec["name"], multi)
    if ambiguous:
        W.append(finding("bbox_ambiguous", ambiguous))
    if exp_bbox:
        bb = design.BoundBox
        got = [bb.XLength, bb.YLength, bb.ZLength]
        tol = chk.get("bbox_tol", 0.05)
        M["design_bbox_mm"] = [round(x, 3) for x in got]
        if any(abs(g - e) > tol for g, e in zip(got, exp_bbox)):
            E.append(finding("bbox_mismatch", "design bbox %s != expected %s (tol %s)"
                             % (M["design_bbox_mm"], exp_bbox, tol),
                             got_mm=M["design_bbox_mm"], expected_mm=exp_bbox))

    # --- declared roots must be inside the parent solid
    for item in chk.get("inside_points", []):
        if item.get("part") and item["part"] != rec["name"]:
            continue
        at = item.get("at_mm")
        if not at:
            continue
        if not design.isInside(V(*[float(x) for x in at]), 1e-6, False):
            E.append(finding("root_disconnected",
                             "%s: point %s is not inside the part, so the feature there is not "
                             "attached" % (item.get("name", "declared point"), at),
                             name=item.get("name"), at_mm=at))

    # --- print orientation
    s = print_oriented(design, P)
    bb = s.BoundBox
    M["print_bbox_mm"] = [round(bb.XLength, 2), round(bb.YLength, 2), round(bb.ZLength, 2)]
    vol = pr.get("build_volume")
    if vol and any(d > v for d, v in zip(sorted(M["print_bbox_mm"][:2]) + [bb.ZLength],
                                         sorted(vol[:2]) + [vol[2]])):
        E.append(finding("build_volume", "part %s does not fit build volume %s"
                         % (M["print_bbox_mm"], vol)))

    # --- mesh health
    mesh = mesh_from_shape(s, P, linear=max(0.02, layer / 10), angular_deg=10)
    for attr, bad, code, msg in (("isSolid", False, "mesh_not_solid", "mesh is not watertight"),
                                 ("hasNonManifolds", True, "mesh_nonmanifold", "mesh has non-manifold edges"),
                                 ("hasSelfIntersections", True, "mesh_self_intersect", "mesh self-intersects")):
        fn = getattr(mesh, attr, None)
        if fn is None:
            continue
        try:
            if bool(fn()) == bad:
                E.append(finding(code, msg))
        except Exception as exc:  # noqa: BLE001
            I.append(finding("mesh_check_unavailable", "mesh check %s unavailable: %s" % (attr, exc)))

    pts, facets = mesh.Topology
    points = np.array([[p.x, p.y, p.z] for p in pts])
    cent, nrm, area = facet_arrays(points, facets)
    zmin = float(points[:, 2].min())

    # --- overhangs / flat down faces, classified
    ovh = overhang_mask(nrm, cent, pr.get("max_overhang_deg", 45), zmin, layer)
    flat = flat_down_mask(nrm, cent, zmin, layer)
    steep = ovh & ~flat
    M["overhang_area_mm2"] = round(float(area[steep].sum()), 2)
    M["flat_downward_area_mm2"] = round(float(area[flat].sum()), 2)
    if M["overhang_area_mm2"] > 1.0:
        msg = finding("overhang_steep",
                      "%.1f mm2 of overhang steeper than %s deg; regions: %s"
                      % (M["overhang_area_mm2"], pr.get("max_overhang_deg", 45),
                         group_regions(cent, area, steep)),
                      regions=group_regions(cent, area, steep))
        (W if pr.get("supports_allowed") else E).append(msg)
    if M["flat_downward_area_mm2"] > 1.0:
        try:
            _, regions = classify_down_faces(s, points, facets, cent, nrm, area, zmin, P)
        except Exception as exc:  # noqa: BLE001 - heuristic; never fail silently
            regions = None
            W.append(finding("flat_uncertain",
                             "support classification failed (%s); inspect the renders and the slicer "
                             "with supports off before trusting this part" % exc))
        if regions is not None:
            M["down_face_regions"] = [{k: v for k, v in r.items() if k != "facets"} for r in regions]
            for severity, item in _region_findings(P, regions):
                {"error": E, "warning": W, "info": I}[severity].append(item)

    contact = bed_contact_area(nrm, cent, area, zmin)
    M["bed_contact_mm2"] = round(contact, 2)
    footprint = bb.XLength * bb.YLength
    if contact < 25 or (footprint > 0 and contact / footprint < 0.1):
        W.append(finding("small_bed_contact",
                         "small bed contact (%.1f mm2); consider re-orienting or a brim" % contact))
    min_xy = min(bb.XLength, bb.YLength)
    if min_xy > 0 and bb.ZLength / min_xy > 4:
        W.append(finding("tall_thin", "tall and thin (height/width %.1f); may wobble or snap at "
                         "layer lines" % (bb.ZLength / min_xy)))

    # --- wall thickness
    found, thin, n = wall_thickness_scan(s, min_wall)
    M["min_wall_found_mm"] = found
    M["wall_samples"] = n
    if thin:
        E.append(finding("wall_thin", "walls thinner than %s mm: %s" % (min_wall, thin), spots=thin))

    # --- horizontal holes
    holes = horizontal_holes(s, pr.get("teardrop_above_d", 5))
    if holes:
        I.append(finding("horizontal_hole", "horizontal holes >= %s mm will sag at the top; use "
                         "teardrop_hole or ream: %s" % (pr.get("teardrop_above_d", 5), holes),
                         holes=holes))
    return res


# ---------------------------------------------------------------- whole-project checks
def check_relations(P, designs, report):
    """Measured clearance / interference between named parts, in design (assembled) position."""
    rows = []
    for rel in P.get("checks", {}).get("relations", []):
        name = rel.get("name") or "%s_%s" % (rel.get("a"), rel.get("b"))
        row = {"name": name, "a": rel.get("a"), "b": rel.get("b"), "ok": True, "problems": []}
        sa, sb = designs.get(rel.get("a")), designs.get(rel.get("b"))
        if sa is None or sb is None:
            row["ok"] = False
            row["problems"].append("unknown part name; parts are: %s" % ", ".join(sorted(designs)))
            rows.append(row)
            continue
        try:
            d = float(sa.distToShape(sb)[0])
        except Exception as exc:  # noqa: BLE001
            row["ok"] = False
            row["problems"].append("distToShape failed: %s" % exc)
            rows.append(row)
            continue
        row["distance_mm"] = round(d, 3)
        tol = float(rel.get("tol_mm", 0.05))
        if "min_distance_mm" in rel and d < float(rel["min_distance_mm"]) - tol:
            row["problems"].append("distance %.3f mm < required min %s mm"
                                   % (d, rel["min_distance_mm"]))
        if "max_distance_mm" in rel and d > float(rel["max_distance_mm"]) + tol:
            row["problems"].append("distance %.3f mm > allowed max %s mm (no engagement / cannot reach)"
                                   % (d, rel["max_distance_mm"]))
        if any(k in rel for k in ("min_interference_mm3", "max_interference_mm3")):
            try:
                inter = float(sa.common(sb).Volume)
                row["interference_mm3"] = round(inter, 4)
                tvol = float(rel.get("tol_mm3", 0.01))
                if "min_interference_mm3" in rel and inter < float(rel["min_interference_mm3"]) - tvol:
                    row["problems"].append("interference %.4f mm3 < required min %s (no engagement)"
                                           % (inter, rel["min_interference_mm3"]))
                if "max_interference_mm3" in rel and inter > float(rel["max_interference_mm3"]) + tvol:
                    row["problems"].append("interference %.4f mm3 > allowed max %s (will not close)"
                                           % (inter, rel["max_interference_mm3"]))
            except Exception as exc:  # noqa: BLE001
                row["problems"].append("common() failed: %s" % exc)
        row["ok"] = not row["problems"]
        if not row["ok"]:
            row["text"] = "; ".join(row["problems"])
        rows.append(row)
    report["relations"] = rows
    return rows


def check_coupon(P, report):
    """A coupon must be a section of the real part, never a thick block stand-in."""
    c = P.get("coupon") or {}
    names = [p["name"] for p in report["parts"]]
    if not c.get("enabled"):
        stray = [n for n in names if n.lower().startswith("coupon")]
        if stray:
            return [finding("coupon_not_section",
                            "parts %s look like coupons but params.coupon is disabled: a coupon "
                            "modelled on its own does not reproduce the real wall, lip or flex. "
                            "Declare it as a section of the real part." % ", ".join(stray))]
        return []
    out = []
    if not c.get("source") or not c.get("section_mm"):
        out.append(finding("coupon_not_section",
                           "coupon is enabled without source+section_mm: a block coupon does not "
                           "reproduce the real wall, lip or flex. Cut the coupon out of the part."))
    prefix = c.get("name") or "coupon"
    if not any(n == prefix or n.startswith(prefix + "_") for n in names):
        out.append(finding("coupon_missing", "coupon is enabled but no exported part is named %s*; "
                           "check build.py" % prefix))
    return out


def main():
    import Part
    from cadlib import load_params, read_json, write_json

    P = load_params()
    report = {"pass": False, "parts": [], "relations": []}
    try:
        status = read_json("build_status.json")
        if not status or not status.get("ok"):
            raise RuntimeError("build_status.json missing or build failed; run build.py first")
        designs = {rec["name"]: Part.read(rec["step"]) for rec in status["parts"]}
        multi = len(designs) > 1
        for rec in status["parts"]:
            report["parts"].append(check_part(rec, P, designs, multi))
        check_relations(P, designs, report)
        coupon = check_coupon(P, report)
        if coupon:
            report["coupon"] = coupon
            target = next((p for p in report["parts"] if p["name"].startswith("coupon")), report["parts"][0])
            target["warnings"] += coupon
        report["pass"] = (all(not p["errors"] for p in report["parts"])
                          and all(r["ok"] for r in report.get("relations", [])))
    except Exception:  # noqa: BLE001
        report["error"] = traceback.format_exc()
    write_json("report.json", report)
    print("CHECK", "PASS" if report["pass"] else "FAIL")
    for p in report["parts"]:
        for k in ("errors", "warnings", "info"):
            for m in p[k]:
                print("  [%s] %s: %s" % (k[:-1].upper() if k != "info" else "INFO", p["name"],
                                         m.get("text", m) if isinstance(m, dict) else m))
    for rel in report.get("relations", []):
        print("  [REL] %s: %s" % (rel["name"], rel.get("text", "ok")))
    if "error" in report:
        print(report["error"])


if not os.environ.get("FCP_NO_MAIN"):
    main()
