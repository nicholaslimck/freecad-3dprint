# FreeCAD Part scripting reference

Stick to the calls in this file. If you need something that isn't here, write a
3-line probe script, run it with FreeCADCmd, and confirm the call exists before
building on it. Don't guess method names; FreeCAD's API has many near-misses.

All units are mm and degrees unless noted. `from FreeCAD import Vector as V`.

## Contents
1. Primitives
2. 2D profiles -> solids
3. Booleans
4. Transforms (in-place gotcha)
5. Fillets and chamfers
6. Selecting faces and edges
7. Shells, mirrors, patterns
8. Text
9. Inspecting shapes
10. Things to avoid
11. Error messages and what they usually mean

## 1. Primitives
```python
Part.makeBox(x, y, z, V(px, py, pz))                  # min corner at p
Part.makeCylinder(r, h, V(base), V(axis))
Part.makeCone(r1, r2, h, V(base), V(axis))           # r1 at base
Part.makeSphere(r, V(center))
Part.makeTorus(R, r, V(center), V(axis))
Part.makeWedge(xmin, ymin, zmin, z2min, x2min, xmax, ymax, zmax, z2max, x2max)  # rarely needed
```

## 2. 2D profiles -> solids
```python
wire = Part.makePolygon([V(0,0,0), V(10,0,0), V(10,5,0), V(0,0,0)])   # closed: repeat first point
face = Part.Face(wire)
solid = face.extrude(V(0, 0, h))                       # prism
solid = face.revolve(V(0,0,0), V(0,0,1), 360)          # lathe; profile must not cross the axis

circle = Part.makeCircle(r, V(cx, cy, 0), V(0, 0, 1))  # edge
face = Part.Face(Part.Wire(circle))

# Arc through 3 points, then mix with lines
arc = Part.Arc(V(0,0,0), V(5,5,0), V(10,0,0)).toShape()
line = Part.LineSegment(V(10,0,0), V(0,0,0)).toShape()
face = Part.Face(Part.Wire([arc, line]))

# Face with holes: outer wire first, then inner wires
face = Part.Face([outer_wire, inner_wire])             # if this fails: Part.Face(outer).cut(Part.Face(inner))

# Loft and sweep
loft = Part.makeLoft([wire_bottom, wire_top], True)    # True = solid
sweep = Part.Wire(path_edges).makePipeShell([profile_wire], True, True)  # (profiles, solid, frenet)
```

## 3. Booleans
```python
a.fuse(b)            # union; fuse a list: a.fuse([b, c, d])
a.cut(b)             # subtract; cut a list: a.cut([b, c])
a.common(b)          # intersection
result.removeSplitter()   # merge coplanar faces left by booleans; call once at the end
```
Always let cutting tools overshoot the surface by about 0.01 mm (`cadlib.EPS`).
Coincident faces cause invalid shapes or zero-thickness skins.

Fusing or cutting a list in one call is much faster and more robust than looping one tool at a time when there are many tools (e.g. 50 vent holes).

## 4. Transforms (in-place gotcha)
```python
s2 = s.copy(); s2.translate(V(10, 0, 0))                # translate() MUTATES the shape in place
s2 = s.copy(); s2.rotate(V(0,0,0), V(0,0,1), 90)        # (center, axis, degrees), mutates
s2 = s.mirror(V(0,0,0), V(1,0,0))                       # returns new shape, mirrors across plane with normal X
s2 = s.transformGeometry(App.Matrix())                  # general matrix; returns new shape
pl = App.Placement(V(10,0,0), App.Rotation(V(0,0,1), 90)); s2 = s.copy(); s2.Placement = pl
```
The bug to watch for is `s.translate(...)` on a shape that's reused elsewhere. Copy first.

## 5. Fillets and chamfers
```python
s.makeFillet(r, edges)              # edges: list of Edge objects from s itself
s.makeChamfer(size, edges)
```
- Prefer `cadlib.safe_fillet / safe_chamfer`: OCC failures become a warning instead of a crash.
- Fillet **before** cutting features that intersect the filleted edge, or select edges after the cut. Edge lists from an earlier shape aren't valid after a boolean.
- Radius must be smaller than half the thinnest adjacent face. If a fillet fails, try a smaller radius or fewer edges before trying anything clever.
- Rounded vertical corners on a box: `cadlib.rounded_box`, or fillet the 2D profile before extruding, which is the most robust option.

## 6. Selecting faces and edges
Select by geometry, never by index. Indices change whenever topology changes.
```python
top = max((f for f in s.Faces if abs(f.normalAt(0,0).z - 1) < 1e-6), key=lambda f: f.CenterOfMass.z)
edges = [e for e in s.Edges if isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - 1.7) < 1e-3]
edges = cadlib.edges_at_z(s, z)                       # all edges flat at height z
outer = cadlib.largest_face_at_z(s, z).OuterWire.Edges
f.Surface                                              # Part.Plane, Part.Cylinder (Radius, Axis, Center), ...
e.Curve                                                # Part.Line, Part.Circle (Radius, Center, Axis), ...
f.BoundBox, e.BoundBox, f.CenterOfMass, f.Area, e.Length
```
`normalAt(u, v)` on a plane is constant, so `(0, 0)` is fine. On curved faces use the
middle of `f.ParameterRange`.

## 7. Shells, mirrors, patterns
```python
# Hollow box open at the top: remove the top face, walls grow inward with negative thickness
top = max(s.Faces, key=lambda f: f.CenterOfMass.z)
shell = s.makeThickness([top], -wall, 1e-3)
```
`makeThickness` is fragile on complex shapes. For enclosures, `outer.cut(inner_box)` with an
inner rounded box is often more reliable.

Linear or polar patterns: build one tool, copy and transform it N times, then fuse or cut the whole list in one call.

## 8. Text
```python
wires = Part.makeWireString("ABC", r"C:\Windows\Fonts\arialbd.ttf", 6.0)  # size in mm (cap height-ish)
faces = [Part.Face(w) for w in wires]   # some glyphs need Part.Face(list_of_wires) for counters
text = Part.makeCompound([f.extrude(V(0, 0, 0.6)) for f in faces])
```
Use a bold font for printing. Letter stroke should be at least 2x the nozzle diameter.
Glyph faces with counters (O, A, 8) sometimes come out filled. Check them in the renders.

## 9. Inspecting shapes
```python
s.isValid(); s.check(True)       # check() raises with a reason when invalid
len(s.Solids); s.Volume; s.Area; s.BoundBox (XMin, XLength, ..., DiagonalLength)
len(s.Shells)                    # a solid normally has the same number of shells
s.isInside(V(x,y,z), 1e-4, True) # point containment
s.distToShape(other)[0]          # min distance between shapes (clearance checks between parts)
s.common(other)                  # intersection; use a box to cut a coupon or a section
Part.read(path)                  # load STEP/BREP
s.exportStep(path)
```
`BoundBox` is conservative: after a fillet it can extend a few tenths of a mm past
the nominal surface even though volume was removed. Set `checks.bbox_mm` from the
built part, not the drawing.

A floating feature shows up as a second entry in `s.Solids`. Check `Solids` after
every build; a hook whose root gusset does not touch its parent is still exported
as valid geometry.

### Working from an existing model

```python
part = Part.read(r"C:\ref\reference.step")   # real faces and solids: booleans work
part.BoundBox, part.Volume, len(part.Solids)

import Mesh
mesh = Mesh.Mesh(r"C:\ref\reference.3mf")    # STL/3MF: triangles only
mesh.CountPoints, mesh.BoundBox, mesh.Volume
shape = Part.Shape(mesh)                     # simple watertight meshes only; often fails
```

A STEP is a B-rep: use it as a reference body, or `cut`/`common` against it. An
STL/3MF is a mesh with no feature tree, dimensions or editable faces. Measure it,
write the dimensions into `spec.md`, and **rebuild the part parametrically**; keep
the mesh as a visual or subtractive reference. A 3MF may contain several objects
and transforms, so check what actually loaded before trusting its size.

## 10. Things to avoid
- **Sketcher and its constraint solver from scripts.** It's verbose and fails silently. Build profiles from polygons, arcs and circles instead.
- **PartDesign Body/Pad/Pocket from scripts.** It works, but the feature-tree semantics, like a single solid per body and attachment, add many failure modes without any benefit for a scripted part.
- **Threads modelled as helical sweeps.** They're slow and fragile. Prefer heat-set inserts, nuts in hex pockets, or self-tapping holes. See printability.md.
- **`import Draft` in FreeCADCmd.** Parts of Draft need the GUI.
- **Very small fillets (< 0.2 mm).** They don't print and they bloat the mesh.

## 11. Error messages and what they usually mean
| Message | Usual cause |
|---|---|
| `BRep_API: command not done` | fillet/chamfer radius too big, or edges from an old shape |
| `Shape is null` | a boolean produced nothing: tool doesn't intersect, or wrong placement |
| `report: 2+ solids` | a cut split the part, or a fuse had a gap between bodies |
| invalid shape after boolean | coincident faces: add EPS overshoot |
| `Part.OCCError: Failed to create face from wire` | wire isn't closed or isn't planar |
| `Unexpected UTF-8 BOM` | the script starts with a UTF-8 BOM; see below |
| `AttributeError: 'Part.Wire' object has no attribute 'edges'` | Python API names are capitalised: `Wire.Edges`, `Shape.Solids` |

## 12. Running scripts headless

**`__name__` is not `"__main__"` under FreeCADCmd.** A script that ends with

```python
if __name__ == "__main__":
    main()
```

can run to completion without executing `main()` and without an error. Call
`main()` directly at the bottom of a headless script, or wrap it explicitly:

```
FreeCADCmd.exe -c "import build; build.main()"
```

The kit scripts call `main()` directly for this reason.

**No UTF-8 BOM.** FreeCADCmd refuses a file that starts with one. Python's
`open(path, "w", encoding="utf-8")` does not write a BOM, but Windows PowerShell
5.1's `Set-Content -Encoding UTF8` does. Use `cadlib.write_text(path, text)`, and
`fcp/doctor.py` scans the project for BOMs.

**Exit codes are not reliable** for FreeCADCmd. Every kit step writes
`.out/<step>_status.json` or `.out/report.json`; read those instead.

