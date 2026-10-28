"""End-to-end acceptance cases for the skill's checks.

Run:  python tests/e2e_cases.py [--keep]

Needs FreeCADCmd: $env:FREECAD_CMD, else a common Program Files install.
Builds throwaway projects under %TEMP%/opencode/fcp-e2e. Never touches a real
project. FreeCADCmd's exit code is unreliable, so every case asserts on the
.out/*.json status files instead.

Cases (from the improvement handoff):
  1. shelf attached at one end          -> flat_cantilever, not a bridge
  2. strap between two towers           -> flat_bridge
  3. disconnected hook                  -> components_unexpected with bboxes
  4. accept the cantilever + preview    -> gate goes printable, without a rebuild
  5. UTF-8 BOM                          -> doctor fails with a BOM message
  6. coupon without a section           -> coupon_not_section warning
  7. coupon cut from the real part      -> exported, checked, no coupon warning
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "skills", "freecad-3dprint", "kit")
WORK = os.path.join(tempfile.gettempdir(), "opencode", "fcp-e2e")

BUILD = '''"""E2E case: {name}."""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.environ.get("FCP_PROJECT") or os.getcwd(), "fcp"))
from cadlib import *  # noqa: E402,F401,F403

P = load_params()
WARN = []


{body}


def main():
    status = {{"ok": False, "warnings": WARN}}
    try:
        result = build(P)
        parts = dict(result) if isinstance(result, dict) else {{P.get("name", "part"): result}}
        parts = add_coupons(parts, P, build, WARN)
        records, fcstd = export_all(parts, P)
        status.update(ok=True, parts=records, fcstd=fcstd)
    except Exception:  # noqa: BLE001
        status["error"] = traceback.format_exc()
    write_json("build_status.json", status)
    print("BUILD", "OK" if status["ok"] else "FAILED")
    if not status["ok"]:
        print(status["error"])


main()
'''

CANTILEVER = '''
def build(params):
    g = params["geometry"]
    wall = box(g["wall"], g["width"], g["height"], at=(0, -g["width"] / 2.0, 0))
    shelf = box(g["depth"], g["width"], g["lip"], at=(g["wall"], -g["width"] / 2.0, g["shelf_z"]))
    return wall.fuse(shelf).removeSplitter()
'''

BRIDGE = '''
def build(params):
    g = params["geometry"]
    w = g["width"]
    left = box(g["tower"], w, g["height"], at=(0, -w / 2.0, 0))
    right = box(g["tower"], w, g["height"], at=(g["tower"] + g["span"], -w / 2.0, 0))
    strap = box(g["span"], g["strap_w"], g["strap_t"], at=(g["tower"], -g["strap_w"] / 2.0, g["strap_z"]))
    return left.fuse([right, strap]).removeSplitter()
'''

DISCONNECTED = '''
def build(params):
    g = params["geometry"]
    wall = box(g["wall"], g["width"], g["height"], at=(0, -g["width"] / 2.0, 0))
    hook = box(g["hook_len"], g["hook_w"], g["hook_t"], at=(g["wall"] + g["gap"], -g["hook_w"] / 2.0, g["hook_z"]))
    return wall.fuse(hook).removeSplitter()
'''

COUPON = '''
def build(params):
    g = params["geometry"]
    outer = rounded_box(g["length"], g["width"], g["height"], 2.0, center_xy=True)
    inner = box(g["length"] - 2 * g["wall"], g["width"] - 2 * g["wall"],
                g["height"] - g["floor"], center_xy=True, at=(0, 0, g["floor"]))
    return outer.cut(inner).removeSplitter()
'''


def find_freecad():
    cand = os.environ.get("FREECAD_CMD")
    if cand and os.path.exists(cand):
        return cand
    hits = sorted(glob.glob(r"C:\Program Files\FreeCAD*\bin\FreeCADCmd.exe"))
    if hits:
        return hits[-1]
    raise SystemExit("FreeCADCmd.exe not found; set $env:FREECAD_CMD")


def params(name, geometry, bbox, **checks):
    chk = {"bbox_mm": {name: bbox}, "bbox_tol": 0.05, "expected_solids": 1,
           "inside_points": [], "relations": [], "accept": []}
    chk.update(checks)
    return {
        "name": name,
        "version": 1,
        "geometry": geometry,
        "print": {"process": "fdm", "nozzle": 0.4, "layer_height": 0.2, "min_wall": 0.8,
                  "max_overhang_deg": 45, "supports_allowed": False, "support_gap_mm": 0.6,
                  "rotate": [], "build_volume": [256, 256, 256],
                  "elephant_foot_chamfer": 0.0, "teardrop_above_d": 5,
                  "preview": {"done": False, "supports_off": False, "by": "", "date": "",
                              "evidence": ""}},
        "export": {"linear_deflection": 0.01, "angular_deflection_deg": 5},
        "checks": chk,
        "part_meta": {name: {"purpose": "e2e case"}},
        "render": {"features": []},
        "coupon": {"enabled": False, "source": "", "section_mm": [], "name": "coupon",
                   "purpose": "", "assembly": "", "variants": [], "test_steps": [],
                   "pass_criteria": []},
        "slicer": {"type": "prusa", "exe": "", "config": "", "args": []},
    }


class Case:
    def __init__(self, name, body, p):
        self.name = name
        self.dir = os.path.join(WORK, name)
        self.workspace = os.path.join(self.dir, ".freecad-3dprint")
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.copytree(KIT, self.workspace)
        self.write("build.py", BUILD.format(name=name, body=body))
        self.write_params(p)

    def write(self, rel, text):
        path = os.path.join(self.workspace, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def write_params(self, p):
        self.p = p
        self.write("params.json", json.dumps(p, indent=2))

    def run(self, script):
        env = dict(os.environ, FCP_PROJECT=self.workspace)
        proc = subprocess.run([find_freecad(), os.path.join(self.workspace, script)],
                              cwd=self.workspace, env=env, capture_output=True, text=True,
                              timeout=900)
        return (proc.stdout or "") + (proc.stderr or "")

    def json(self, rel):
        path = os.path.join(self.workspace, ".out", rel)
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def checkout(self):
        self.run("build.py")
        self.run(os.path.join("fcp", "check_print.py"))
        self.run(os.path.join("fcp", "render_views.py"))
        self.run(os.path.join("fcp", "gate.py"))


def codes(part):
    return [w.get("code") for w in part.get("warnings", [])]


def main(argv):
    failures = []

    def expect(cond, msg):
        if not cond:
            failures.append(msg)
            print("  FAIL " + msg)

    print("1. cantilever shelf")
    a = Case("cantilever", CANTILEVER,
             params("cantilever", {"wall": 3, "width": 20, "height": 20, "depth": 4,
                                   "lip": 0.8, "shelf_z": 10}, [7, 20, 20]))
    a.checkout()
    report = a.json("report.json")
    part = report["parts"][0]
    expect(report["pass"], "cantilever report should pass (warnings only)")
    expect("flat_cantilever" in codes(part), "cantilever shelf must report flat_cantilever")
    expect("flat_bridge" not in codes(part), "cantilever shelf must not report flat_bridge")
    gate = a.json("print_gate.json")
    expect(not gate["printable"], "gate must refuse before triage and preview")
    expect(any("acceptance" in r or "triaged" in r for r in gate["reasons"]),
           "gate must name the untriaged warning")
    expect("not print-verified" in " ".join(gate["reasons"]), "gate must ask for a slicer check")

    print("2. bridge strap")
    b = Case("bridge", BRIDGE,
             params("bridge", {"tower": 3, "span": 16, "width": 20, "height": 20,
                               "strap_w": 12, "strap_t": 0.8, "strap_z": 10}, [22, 20, 20]))
    b.checkout()
    report = b.json("report.json")
    part = report["parts"][0]
    expect("flat_bridge" in codes(part), "two-tower strap must report flat_bridge")
    expect("flat_cantilever" not in codes(part), "two-tower strap must not report cantilever")

    print("3. disconnected hook")
    c = Case("disconnected", DISCONNECTED,
             params("disconnected", {"wall": 3, "width": 20, "height": 20,
                                     "hook_len": 6, "hook_w": 8, "hook_t": 4,
                                     "hook_z": 10, "gap": 0.2}, [9.2, 20, 20]))
    c.checkout()
    report = c.json("report.json")
    expect(not report["pass"], "disconnected hook must fail the checks")
    errors = [e.get("code") for e in report["parts"][0]["errors"]]
    expect("components_unexpected" in errors, "disconnected hook needs components_unexpected")
    finding = next((e for e in report["parts"][0]["errors"]
                    if e.get("code") == "components_unexpected"), {})
    expect(len(finding.get("components", [])) == 2, "component error must list both bodies")

    print("4. accept the cantilever, then try to call it a bridge")
    a.p["checks"]["accept"] = [{
        "code": "flat_cantilever",
        "region_center_mm": [5.0, 0.0, 10.0],
        "reason": "test shelf is intentionally cantilevered",
        "evidence": "coupon print showed no droop with 0.2 mm layers",
        "accepted_by": "e2e",
        "date": "2026-10-28"}]
    a.p["print"]["preview"] = {"done": True, "supports_off": True, "by": "e2e",
                               "date": "2026-10-28", "evidence": "slicer preview checked"}
    a.write_params(a.p)
    a.run(os.path.join("fcp", "check_print.py"))
    report = a.json("report.json")
    expect(report["pass"], "accepting the observed code must not fail the check")
    expect("flat_cantilever" in codes(report["parts"][0]),
           "accepted cantilever stays a warning so the gate can triage it")
    a.run(os.path.join("fcp", "gate.py"))
    gate = a.json("print_gate.json")
    expect(gate["printable"], "gate should be printable after triage + preview: %s" % gate["reasons"])

    a.p["checks"]["accept"][0]["code"] = "flat_bridge"  # false bridge claim
    a.write_params(a.p)
    a.run(os.path.join("fcp", "check_print.py"))
    report = a.json("report.json")
    errors = [e.get("code") for e in report["parts"][0]["errors"]]
    expect(not report["pass"], "declaring a cantilever a bridge must fail")
    expect("declared_bridge_is_cantilever" in errors,
           "false bridge claim needs declared_bridge_is_cantilever: %s" % errors)

    print("5. UTF-8 BOM")
    bom_case = Case("bom", CANTILEVER,
                    params("bom", {"wall": 3, "width": 20, "height": 20, "depth": 4,
                                   "lip": 0.8, "shelf_z": 10}, [7, 20, 20]))
    with open(os.path.join(bom_case.workspace, "build.py"), "rb") as f:
        blob = f.read()
    with open(os.path.join(bom_case.workspace, "build.py"), "wb") as f:
        f.write(b"\xef\xbb\xbf" + blob)
    bom_case.run(os.path.join("fcp", "doctor.py"))
    doctor = bom_case.json("doctor.json")
    expect(doctor and not doctor["ok"], "doctor must fail on a BOM")
    expect(any("BOM" in p for p in (doctor or {}).get("problems", [])), "doctor must name the BOM")

    print("6. coupon without a section")
    d = Case("coupon_block", COUPON,
             params("coupon_block", {"length": 40, "width": 20, "floor": 1.6, "wall": 1.2,
                                     "height": 12, "lip": 0.8, "eps": 0.01}, [40, 20, 12]))
    d.p["coupon"]["enabled"] = True
    d.write_params(d.p)
    d.checkout()
    report = d.json("report.json")
    expect("coupon_not_section" in codes(report["parts"][0]),
           "enabled coupon without section_mm must warn coupon_not_section")

    print("7. coupon cut from the real part")
    e = Case("coupon_section", COUPON,
             params("coupon_section", {"length": 40, "width": 20, "floor": 1.6, "wall": 1.2,
                                       "height": 12, "lip": 0.8, "eps": 0.01}, [40, 20, 12]))
    e.p["coupon"].update({
        "enabled": True, "source": "coupon_section", "name": "coupon_lip",
        "section_mm": [[-20, -10, 8], [20, 10, 12]],
        "purpose": "wall thickness and lip junction",
        "assembly": "separate part, same orientation as the case",
        "variants": [{"name": "nominal"}],
        "test_steps": ["slice", "flex the lip"],
        "pass_criteria": ["no crack after 20 flexes"]})
    e.write_params(e.p)
    e.checkout()
    status = e.json("build_status.json")
    names = [p["name"] for p in (status or {}).get("parts", [])]
    expect("coupon_lip_nominal" in names, "coupon section must be exported: %s" % names)
    report = e.json("report.json")
    coupon = next((p for p in (report or {}).get("parts", []) if p["name"] == "coupon_lip_nominal"), None)
    expect(coupon is not None, "coupon must be checked like any part")
    expect("coupon_not_section" not in codes(coupon or {}),
           "section coupon must not be warned as a block coupon")

    print()
    if failures:
        print("FAILED %d check(s)" % len(failures))
        for f in failures:
            print("  - " + f)
        return 1
    print("ALL E2E CASES PASSED  (%s)" % WORK)
    if "--keep" not in argv:
        shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
