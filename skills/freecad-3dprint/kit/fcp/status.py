"""Answer "where is the current design?" without reading five JSON files.

Run with:  FreeCADCmd.exe fcp\\status.py   (or run.ps1 -Step status; no FreeCAD needed)

Prints the workspace, the current version, the gate state and the exact file to
print, and writes the same to .out/status.json. Read-only: it never builds.
"""
import json
import os
import sys
import time


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _stem(params):
    name = params.get("name", "part")
    v = params.get("version")
    return name if v in (None, "") else "%s_v%s" % (name, v)


def status(project):
    """Current version, released folder and next action for a workspace."""
    out = os.path.join(project, ".out")
    params = _read(os.path.join(project, "params.json")) or {}
    manifest = _read(os.path.join(out, "manifest.json"))
    gate = _read(os.path.join(out, "print_gate.json"))
    sliced = _read(os.path.join(out, "slice_report.json"))
    stem = _stem(params)
    release = os.path.join(os.path.dirname(os.path.abspath(project)), "print", stem)

    result = {
        "workspace": os.path.abspath(project),
        "stem": stem,
        "version": params.get("version"),
        "parts": [],
        "slice_this": [],
        "release_dir": release if os.path.isdir(release) else "",
        "gate": None,
        "sliced": bool(sliced and sliced.get("ok")),
        "next": "",
    }
    if manifest:
        for part in manifest.get("parts", []):
            result["parts"].append({
                "name": part.get("name"),
                "slice_this": part.get("slice_this") or part.get("3mf") or part.get("stl"),
                "step": part.get("step"),
                "purpose": part.get("purpose", ""),
            })
            if part.get("slice_this") or part.get("3mf") or part.get("stl"):
                result["slice_this"].append(part.get("slice_this") or part.get("3mf") or part.get("stl"))
    if gate:
        result["gate"] = {
            "printable": bool(gate.get("printable")),
            "reasons": gate.get("reasons", []),
            "verified": ((gate.get("checks") or {}).get("preview") or {}).get("mode", ""),
        }

    if not manifest:
        result["next"] = "no build yet: run run.ps1"
    elif not gate:
        result["next"] = "not gated yet: run run.ps1"
    elif not gate.get("printable"):
        result["next"] = "blocked: " + (gate.get("reasons") or ["see .out/print_gate.json"])[0]
    elif result["release_dir"]:
        result["next"] = "released: " + result["release_dir"]
    else:
        result["next"] = "verified but not released: run run.ps1 -Step release"
    return result


def main():
    project = os.environ.get("FCP_PROJECT") or os.getcwd()
    result = status(project)
    result["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = os.path.join(project, ".out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "status.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, indent=2)
    print("WORKSPACE", result["workspace"])
    print("CURRENT  ", result["stem"])
    for part in result["parts"]:
        print("PART     ", "%s: %s" % (part["name"], part["slice_this"]))
    if result["gate"] is None:
        print("GATE      not gated yet")
    else:
        print("GATE     ", "printable" if result["gate"]["printable"] else "not printable")
        for reason in result["gate"]["reasons"]:
            print("          - " + reason)
    if result["slice_this"]:
        print("SLICE    ", result["slice_this"][0] if len(result["slice_this"]) == 1
              else ", ".join(result["slice_this"]))
    print("RELEASE  ", result["release_dir"] or "(not released)")
    print("NEXT     ", result["next"])
    sys.stdout.flush()


if not os.environ.get("FCP_NO_MAIN"):
    main()  # FreeCADCmd does not set __name__ == "__main__"
