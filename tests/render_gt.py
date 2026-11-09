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


def main(case, out):
    import render_lines as rl
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


def _args():
    """freecadcmd opens any argv that looks like a path, so args come from the env."""
    return os.environ.get("FCP_GT_CASE", "box"), os.environ["FCP_GT_OUT"]


if __name__ == "__main__":
    main(*_args())
else:  # freecadcmd sets __name__ to the file stem
    main(*_args())
