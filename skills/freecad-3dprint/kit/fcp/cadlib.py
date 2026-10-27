"""Shared helpers for FreeCAD 3D-print projects.

Runs inside FreeCAD's bundled Python (FreeCADCmd.exe). Units are millimetres.
Imported by build.py, check_print.py and render_views.py.

Conventions:
  * Every helper returns a NEW shape. FreeCAD's shape.translate()/rotate()
    modify in place, so helpers copy first.
  * Hole helpers take the point where the hole ENTERS the material and the
    direction it drills in (default straight down, -Z).
"""
import json
import math
import os

import FreeCAD as App
import Part
from FreeCAD import Vector as V

EPS = 0.01  # overshoot for boolean cuts so faces never coincide


# ---------------------------------------------------------------- project I/O
def project_dir():
    return os.environ.get("FCP_PROJECT") or os.getcwd()


def out_dir():
    d = os.path.join(project_dir(), "out")
    os.makedirs(d, exist_ok=True)
    return d


def load_params():
    with open(os.path.join(project_dir(), "params.json"), encoding="utf-8") as f:
        return json.load(f)


def write_json(name, data):
    path = os.path.join(out_dir(), name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def read_json(name):
    path = os.path.join(out_dir(), name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _v(p):
    return App.Vector(p) if isinstance(p, App.Vector) else V(*p)  # copy: callers normalize() in place


# ---------------------------------------------------------------- primitives
def box(x, y, z, at=(0, 0, 0), center_xy=False):
    """Axis-aligned box. `at` is the min corner, or the bottom-centre if center_xy."""
    at = _v(at)
    if center_xy:
        at = at - V(x / 2.0, y / 2.0, 0)
    return Part.makeBox(x, y, z, at)


def cyl(r, h, at=(0, 0, 0), axis=(0, 0, 1)):
    return Part.makeCylinder(r, h, _v(at), _v(axis))


def rounded_box(x, y, z, r, at=(0, 0, 0), center_xy=False):
    """Box with its vertical edges rounded to radius r (r=0 -> plain box)."""
    b = box(x, y, z, at, center_xy)
    if r <= 0:
        return b
    vertical = [e for e in b.Edges if _is_line_along(e, V(0, 0, 1))]
    return b.makeFillet(r, vertical)


def extrude_polygon(points_xy, height, z0=0.0):
    """Closed polygon in the XY plane extruded up by `height`."""
    pts = [V(x, y, z0) for x, y in points_xy]
    if (pts[0] - pts[-1]).Length > 1e-9:
        pts.append(pts[0])
    face = Part.Face(Part.makePolygon(pts))
    return face.extrude(V(0, 0, height))


# ---------------------------------------------------------------- holes
def hole(shape, d, depth, at, axis=(0, 0, -1)):
    """Cut a plain hole. Use depth=None for a through hole."""
    a = _v(axis).normalize()
    if depth is None:
        depth = shape.BoundBox.DiagonalLength
    tool = Part.makeCylinder(d / 2.0, depth + EPS, _v(at) - a * EPS, a)
    return shape.cut(tool)


def counterbore(shape, d, depth, cb_d, cb_depth, at, axis=(0, 0, -1)):
    a = _v(axis).normalize()
    s = hole(shape, d, depth, at, a)
    tool = Part.makeCylinder(cb_d / 2.0, cb_depth + EPS, _v(at) - a * EPS, a)
    return s.cut(tool)


def countersink(shape, d, depth, head_d, at, axis=(0, 0, -1)):
    """90-degree countersink (metric flat-head screws)."""
    a = _v(axis).normalize()
    s = hole(shape, d, depth, at, a)
    cone_h = (head_d - d) / 2.0
    tool = Part.makeCone(head_d / 2.0 + EPS, d / 2.0, cone_h + EPS, _v(at) - a * EPS, a)
    return s.cut(tool)


def teardrop_hole(shape, d, length, at, axis=(1, 0, 0), up=(0, 0, 1)):
    """Horizontal hole with a 45-degree pointed roof so it prints without supports.

    `at` is the hole centre on the entry face, `axis` the drilling direction
    (must be horizontal in PRINT orientation), `up` the print-up direction in
    design coordinates.
    """
    a = _v(axis).normalize()
    u = _v(up).normalize()
    w = u.cross(a).normalize()
    r = d / 2.0
    c = _v(at) - a * EPS
    k = r / math.sqrt(2.0)

    def p(x, y):
        return c + w * x + u * y

    rhombus = Part.Face(Part.makePolygon([p(0, 0), p(k, k), p(0, r * math.sqrt(2.0)), p(-k, k), p(0, 0)]))
    tip = rhombus.extrude(a * (length + 2 * EPS))
    body = Part.makeCylinder(r, length + 2 * EPS, c, a)
    return shape.cut(body.fuse(tip))


# ---------------------------------------------------------------- edges
def _is_line_along(edge, direction, tol=1e-6):
    if not isinstance(edge.Curve, (Part.Line, Part.LineSegment)):
        return False
    t = edge.Vertexes[-1].Point - edge.Vertexes[0].Point
    if t.Length < tol:
        return False
    return abs(abs(t.normalize().dot(direction)) - 1.0) < 1e-6


def edges_where(shape, pred):
    return [e for e in shape.Edges if pred(e)]


def _flat_at_z(edge, z, tol=1e-4):
    return (all(abs(v.Point.z - z) < tol for v in edge.Vertexes)
            and abs(edge.BoundBox.ZMax - edge.BoundBox.ZMin) < tol)


def edges_at_z(shape, z, tol=1e-4):
    """Edges lying entirely at height z (design coordinates)."""
    return edges_where(shape, lambda e: _flat_at_z(e, z, tol))


def largest_face_at_z(shape, z, tol=1e-4):
    """Largest planar face lying flat at height z, e.g. the top face of a plate."""
    flat = [f for f in shape.Faces
            if abs(f.BoundBox.ZMin - z) < tol and abs(f.BoundBox.ZMax - z) < tol]
    if not flat:
        raise ValueError("no flat face at z=%s" % z)
    return max(flat, key=lambda f: f.Area)


def _safe_edge_op(shape, op, size, edges, warnings, label):
    """Run shape.makeFillet/makeChamfer; on OCC failure return `shape` and record a warning."""
    if not edges or size <= 0:
        return shape
    try:
        out = op(size, edges)
        if out.isValid():
            return out
        raise RuntimeError("%s produced invalid shape" % label.split()[0])
    except Exception as exc:  # noqa: BLE001 - OCC raises generic errors
        if warnings is not None:
            warnings.append("%s%s on %d edges failed: %s" % (label, size, len(edges), exc))
        return shape


def safe_fillet(shape, r, edges, warnings=None):
    """Fillet; on OCC failure return the unfilleted shape and record a warning."""
    return _safe_edge_op(shape, shape.makeFillet, r, edges, warnings, "fillet r=")


def safe_chamfer(shape, size, edges, warnings=None):
    return _safe_edge_op(shape, shape.makeChamfer, size, edges, warnings, "chamfer ")


def chamfer_bed_edges(shape, size, P, warnings=None):
    """Elephant-foot compensation: chamfer the outer edges touching the bed.

    Works in design coordinates by finding the face that will sit on the bed
    after print orientation is applied.
    """
    if size <= 0:
        return shape
    oriented = print_oriented(shape, P)
    zmin = oriented.BoundBox.ZMin
    bed_idx = [i for i, e in enumerate(oriented.Edges) if _flat_at_z(e, zmin)]
    # Edge order is preserved by copy+rotate+translate, so indices map back.
    edges = [shape.Edges[i] for i in bed_idx]
    return safe_chamfer(shape, size, edges, warnings)


# ---------------------------------------------------------------- orientation
def print_oriented(shape, P):
    """Copy of `shape` rotated into print orientation, centred in XY, sitting on Z=0.

    params.json print.rotate is a list of [axis, degrees] steps applied in order,
    e.g. [[[1,0,0], 90]] stands the part up on its front face.
    """
    s = shape.copy()
    for axis, deg in P.get("print", {}).get("rotate", []):
        s.rotate(V(0, 0, 0), _v(axis), float(deg))
    bb = s.BoundBox
    s.translate(V(-(bb.XMin + bb.XMax) / 2.0, -(bb.YMin + bb.YMax) / 2.0, -bb.ZMin))
    return s


def mesh_from_shape(shape, P, linear=None, angular_deg=None):
    import MeshPart

    ex = P.get("export", {})
    lin = linear if linear is not None else ex.get("linear_deflection", 0.01)
    ang = angular_deg if angular_deg is not None else ex.get("angular_deflection_deg", 5)
    return MeshPart.meshFromShape(Shape=shape, LinearDeflection=lin,
                                  AngularDeflection=math.radians(ang), Relative=False)


# ---------------------------------------------------------------- export
def export_all(result, P):
    """Write FCStd + STEP (design orientation) and STL/3MF (print orientation).

    `result` is a Part.Shape or a dict {part_name: Part.Shape}.
    Returns the parts list stored in build_status.json.
    """
    parts = result if isinstance(result, dict) else {P.get("name", "part"): result}
    od = out_dir()
    doc = App.newDocument(P.get("name", "part").replace("-", "_"))
    records = []
    for name, shape in parts.items():
        obj = doc.addObject("Part::Feature", name.replace("-", "_"))
        obj.Shape = shape
        step = os.path.join(od, name + ".step")
        shape.exportStep(step)
        mesh = mesh_from_shape(print_oriented(shape, P), P)
        stl = os.path.join(od, name + "_print.stl")
        mesh.write(stl)
        rec = {"name": name, "step": step, "stl": stl, "facets": mesh.CountFacets}
        try:
            tmf = os.path.join(od, name + "_print.3mf")
            mesh.write(tmf)
            rec["3mf"] = tmf
        except Exception as exc:  # noqa: BLE001 - older FreeCAD builds lack 3MF
            rec["3mf_error"] = str(exc)
        bb = shape.BoundBox
        rec["design_bbox"] = [round(bb.XLength, 4), round(bb.YLength, 4), round(bb.ZLength, 4)]
        rec["volume_mm3"] = round(shape.Volume, 3)
        records.append(rec)
    doc.recompute()
    fcstd = os.path.join(od, P.get("name", "part") + ".FCStd")
    doc.saveAs(fcstd)
    App.closeDocument(doc.Name)
    return records, fcstd
