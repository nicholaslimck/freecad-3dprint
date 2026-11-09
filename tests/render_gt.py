"""Ground truth for the shape renderer. Run with FreeCADCmd; not collected by pytest.

  FreeCADCmd.exe tests/render_gt.py <case> <out.json>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "freecad-3dprint", "kit", "fcp"))

import Part  # noqa: E402

CASES = {}


def case_box():
    return Part.makeBox(40, 20, 10)


def case_six():
    import render_lines as rl
    out = os.path.join(os.environ["FCP_GT_OUT"] + "_views")
    recs, warnings, timings = rl.render_part(Part.makeBox(40, 20, 10), "box",
                                             (40, 20, 10), out)
    return {"records": recs, "warnings": warnings, "timings": timings}


def case_empty():
    import render_lines as rl
    from render_views import VIEWS
    out = os.path.join(os.environ["FCP_GT_OUT"] + "_views")
    recs, warnings, _timings = rl.render_part(
        Part.makeBox(40, 20, 10), "empty", (40, 20, 10), out,
        views={"iso": ((0.0, 0.0, 0.0), (0, 0, 1)), "front": VIEWS["front"]})
    return {"records": recs, "warnings": warnings}


def case_sheet():
    import render_lines as rl
    out = os.environ["FCP_GT_OUT"] + "_views"
    recs, _warnings, _timings = rl.render_part(Part.makeBox(40, 20, 10), "box",
                                               (40, 20, 10), out)
    sheet = rl.contact_sheet([r["path"] for r in recs], os.path.join(out, "box_sheet.png"),
                             "box   bbox 40.00 x 20.00 x 10.00 mm", rl.ENGINE_FOOTER)
    return {"sheet": sheet, "footer": rl.ENGINE_FOOTER, "records": recs}


def main(case, out):
    import render_lines as rl
    if case in ("six", "empty", "sheet"):
        result = CASES[case]()
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f)
        return
    shape = CASES[case]()
    doc, obj = rl.techdraw_document(shape, "gt_" + case)
    try:
        edges = rl.visible_edges(doc, obj, (0, -1, 0), (0, 0, 1), "front")
        pts = [e.discretize(8) for e in edges]
        ends = [(p.x, p.y) for e in edges for p in (e.firstVertex().Point, e.lastVertex().Point)]
        result = {"n_visible_edges": len(edges),
                  "corners": sorted({(round(x, 6), round(y, 6)) for x, y in ends}),
                  "no_visible_edge_in_the_middle": not any(
                      any(5 < p.x < 35 and 2 < p.y < 8 for p in e) for e in pts)}
    finally:
        rl.close_document(doc)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f)


CASES["box"] = case_box
CASES["six"] = case_six
CASES["empty"] = case_empty
CASES["sheet"] = case_sheet

# freecadcmd sets __name__ to the file stem and opens path-like argv, so the
# shim does the entry-point decision and the case/out come from the environment.
from cli import run  # noqa: E402


def _args():
    return os.environ.get("FCP_GT_CASE", "box"), os.environ["FCP_GT_OUT"]


run(lambda: main(*_args()), module_name=__name__)
