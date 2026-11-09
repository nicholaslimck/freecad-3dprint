"""Occupant fit: does the thing an enclosure is for actually fit inside it?

Nothing else in the kit models a foreign body. A case can pass every
printability check and still be too shallow for the board it holds, because the
board is not a part and has no relations. This module closes that gap.

params.checks.fit[] entries:
  {"name": "board", "part": "base",
   "box_mm": [85, 56, 1.6],          # the occupant, centred on XY
   "at_z_mm": 4.0,                    # where its underside sits
   "component_height_mm": 15.5,       # tallest thing standing on top of it
   "max_interference_mm3": 0.5}       # tolerated overlap

Reported as `fit_collision`, an ERROR rather than a warning: a case that cannot
accept its occupant is not a case, and no amount of triage should let it ship.
"""


def check_fit(P, designs, report):
    """Does every declared occupant fit inside its host part? Appends rows to report["fit"]."""
    entries = (P.get("checks") or {}).get("fit") or []
    if not entries:
        return
    import FreeCAD
    import Part

    rows = []
    for f in entries:
        name = f.get("name") or "occupant"
        row = {"name": name, "part": f.get("part"), "ok": True, "problems": []}
        host = designs.get(f.get("part"))
        if host is None:
            row["ok"] = False
            row["problems"].append("unknown host part %r; parts are: %s"
                                   % (f.get("part"), ", ".join(sorted(designs))))
            rows.append(row)
            continue
        try:
            sx, sy, sz = (float(v) for v in f["box_mm"])
            at = float(f["at_z_mm"])
            ghost = Part.makeBox(sx, sy, sz, FreeCAD.Vector(-sx / 2.0, -sy / 2.0, at))
            clash = float(host.common(ghost).Volume)

            # headroom = host's highest material above the occupant, minus its top.
            # Measured from the host's own bbox so a lid is never mistaken for it.
            hb = host.BoundBox
            above = [fc for fc in host.Faces
                     if fc.BoundBox.ZMin >= at + sz - 1e-6 and fc.BoundBox.ZMax > at + sz + 1e-6]
            ceiling = min((fc.BoundBox.ZMin for fc in above), default=hb.ZMax)
            room = ceiling - (at + sz)
            need = float(f.get("component_height_mm", 0.0))

            row["interference_mm3"] = round(clash, 3)
            row["headroom_mm"] = round(room, 2)
            allowed = float(f.get("max_interference_mm3", 0.5))
            if clash > allowed:
                row["problems"].append("occupant collides with the part: %.1f mm3 > %.1f allowed"
                                       % (clash, allowed))
            if room < need:
                row["problems"].append("only %.1f mm above the occupant, it needs %.1f mm"
                                       % (room, need))
        except Exception as exc:  # noqa: BLE001
            row["ok"] = False
            row["problems"].append("fit check failed: %s" % exc)
        row["ok"] = not row["problems"]
        rows.append(row)
    report["fit"] = rows
