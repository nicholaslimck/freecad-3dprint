"""Print gate: the only place that may call a part printable.

Run with:  FreeCADCmd.exe fcp\\gate.py   (or run.ps1 -Step gate; no FreeCAD needed)

Reads .out/report.json, .out/render_status.json, .out/slice_report.json,
.out/manifest.json and params.json, writes .out/print_gate.json:

  {"printable": bool, "reasons": [...], "untriaged": [...], "checks": {...}}

report.json passing is NOT a print guarantee. The gate also requires:
  * every warning accepted in params.checks.accept with code + reason + evidence
  * renders present (so someone could look at the part)
  * outputs fresh against the current build.py and params.json
  * a clean slice of the current export, or an explicit manual preview record in
    print.preview after looking at the slicer with supports off
"""
import json
import os
import re
import sys
import time

from analysis import design_hash

PROJECT = os.environ.get("FCP_PROJECT") or os.getcwd()
OUT = os.path.join(PROJECT, ".out")


def read_json(name):
    path = os.path.join(OUT, name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def write_json(name, data):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, default=str)


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _accept(finding, accept):
    """Match one finding to an acceptance record. Returns (accepted, note)."""
    if not isinstance(finding, dict):
        return False, "warning is not a structured finding"
    code = finding.get("code")
    region = finding.get("region") or {}
    center = region.get("center_mm")
    for item in accept:
        if item.get("code") != code:
            continue
        declared = item.get("region_center_mm")
        if declared and center:
            tol = max(5.0, 0.25 * float(region.get("span_mm") or 0))
            if sum((float(a) - float(b)) ** 2 for a, b in zip(declared, center)) ** 0.5 > tol:
                continue
        elif declared and not center:
            continue
        if not item.get("reason") or not item.get("evidence"):
            return False, "acceptance for %s needs both reason and evidence" % code
        return True, item.get("reason")
    return False, None


def evaluate(P, report, render, manifest, slice_report):
    reasons, untriaged, checks = [], [], {}

    if not report:
        reasons.append("no .out/report.json; run build.py then check_print.py")
        report = {}
    if report.get("error"):
        reasons.append("check crashed; see report.error")
    if not report.get("pass"):
        reasons.append("checks failed (.out/report.json pass=false)")

    accept = P.get("checks", {}).get("accept", [])
    for part in report.get("parts", []):
        for w in part.get("warnings", []):
            ok, note = _accept(w, accept)
            if not ok:
                row = dict(w) if isinstance(w, dict) else {"text": str(w)}
                row["part"] = part.get("name")
                if note:
                    row["accept_error"] = note
                untriaged.append(row)
    if untriaged:
        reasons.append("%d warning(s) have no acceptance with evidence (checks.accept)" % len(untriaged))

    if not render or not render.get("ok"):
        reasons.append("renders missing or failed (.out/render_status.json)")
    elif render.get("warnings"):
        reasons.append("render warnings: " + "; ".join(str(w) for w in render["warnings"][:4]))

    if not manifest:
        reasons.append("no .out/manifest.json; rerun build.py")
    else:
        for rel, digest in (manifest.get("sources") or {}).items():
            if rel == "design":
                if design_hash(P) != digest:
                    reasons.append("outputs are stale: params.json changed after the build; "
                                   "rerun the pipeline")
                continue
            path = os.path.join(PROJECT, rel)
            if not os.path.exists(path) or sha256(path) != digest:
                reasons.append("outputs are stale: %s changed after the build; rerun the pipeline" % rel)
        for part in manifest.get("parts", []):
            for path in (part.get("files") or {}).values():
                if not os.path.exists(path):
                    reasons.append("manifest lists a missing file: %s" % path)

    slicer_ok = False
    if slice_report and slice_report.get("ok"):
        problems = []
        no_support = not P.get("print", {}).get("supports_allowed")
        blocking = re.compile(r"outside|empty|unsupported", re.I)
        current = {p.get("name"): p.get("sha256", {}).get("3mf") or p.get("sha256", {}).get("stl")
                   for p in (manifest or {}).get("parts", [])}
        for part in slice_report.get("parts", []):
            if not part.get("gcode"):
                problems.append("%s: no G-code produced" % part.get("name"))
            if current and part.get("model_sha256") != current.get(part.get("name")):
                problems.append("%s: sliced a different file than the current export" % part.get("name"))
            for w in part.get("warnings", []):
                if blocking.search(w) or (no_support and re.search(r"support", w, re.I)):
                    problems.append("%s: %s" % (part.get("name"), w))
        if problems:
            reasons.append("slicer reported problems: " + "; ".join(problems[:6]))
        else:
            slicer_ok = True
            checks["preview"] = {"mode": "slicer", "report": ".out/slice_report.json"}

    preview = P.get("print", {}).get("preview") or {}
    if not slicer_ok:
        if preview.get("done") and preview.get("supports_off"):
            checks["preview"] = {"mode": "manual", "by": preview.get("by", ""),
                                 "date": preview.get("date", ""),
                                 "evidence": preview.get("evidence", "")}
        else:
            reasons.append(
                "not print-verified: slice with supports off (run.ps1 -Slice), or look at the slicer "
                "with supports off and record print.preview {done: true, supports_off: true, by, date, "
                "evidence} in params.json")

    return {"printable": not reasons, "reasons": reasons, "untriaged": untriaged,
            "checks": checks, "generated": time.strftime("%Y-%m-%dT%H:%M:%S")}


def main():
    params_path = os.path.join(PROJECT, "params.json")
    try:
        with open(params_path, encoding="utf-8") as f:
            P = json.load(f)
    except (OSError, ValueError) as exc:
        result = {"printable": False, "reasons": ["cannot read params.json: %s" % exc],
                  "untriaged": [], "checks": {}}
    else:
        result = evaluate(P, read_json("report.json"), read_json("render_status.json"),
                          read_json("manifest.json"), read_json("slice_report.json"))
    write_json("print_gate.json", result)
    print("GATE", "PRINTABLE" if result["printable"] else "NOT PRINTABLE")
    for r in result["reasons"]:
        print("  - " + r)
    for w in result["untriaged"][:12]:
        print("  ? [%s] %s: %s" % (w.get("code", "warning"), w.get("part", ""), w.get("text", "")))
    sys.stdout.flush()
    sys.exit(0 if result["printable"] else 1)


if not os.environ.get("FCP_NO_MAIN"):
    main()  # FreeCADCmd does not set __name__ == "__main__"



