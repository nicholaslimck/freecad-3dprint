"""Promote a verified design into the project's print/ folder.

Run with:  FreeCADCmd.exe fcp\\release.py   (or run.ps1 -Step release; no FreeCAD needed)

Refuses unless .out/print_gate.json is printable for the current design. Copies
the current slice target, STEP, FCStd, report, gate and manifest into
<project>/print/<name>_v<version>/ and writes README.md + release.json.

<project> is the parent of the .freecad-3dprint workspace. The print/ folder is
visible and safe to commit; .out/ is the regenerable working area.
"""
import hashlib
import json
import os
import shutil
import sys
import time

from analysis import design_hash


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stem(params):
    name = params.get("name", "part")
    v = params.get("version")
    return name if v in (None, "") else "%s_v%s" % (name, v)


def _readme(params, gate, digest, files, date):
    pr = params.get("print", {})
    preview = (gate.get("checks") or {}).get("preview") or {}
    mode = preview.get("mode", "unknown")
    if mode == "manual":
        verified = "manual preview by %s on %s" % (preview.get("by", ""), preview.get("date", ""))
    else:
        verified = "clean slice with supports off"
    lines = [
        "# %s" % _stem(params),
        "",
        "Released %s from the `.freecad-3dprint` workspace." % date,
        "Design hash: `%s`" % digest[:12],
        "",
        "## Print",
        "- Files are already in print orientation (`print.rotate` = `%s`)." % (pr.get("rotate", []),),
        "- Nozzle %s mm, layer %s mm, supports %s." % (
            pr.get("nozzle", 0.4), pr.get("layer_height", 0.2),
            "allowed" if pr.get("supports_allowed") else "not allowed"),
        "- Verified: %s." % verified,
        "",
        "## Files",
    ]
    lines += ["- `%s` (sha256 `%s...`)" % (f["name"], f["sha256"][:16]) for f in files]
    lines += [
        "",
        "## Verify",
        "`release.json` lists every file hash and the gate status. `report.json` is the check "
        "record, `print_gate.json` the gate record.",
        "",
    ]
    return "\n".join(lines)


def release(project):
    """Copy the verified export for `project` into its sibling print/ folder."""
    out = os.path.join(project, ".out")
    params = _read(os.path.join(project, "params.json")) or {}
    digest = design_hash(params)
    gate = _read(os.path.join(out, "print_gate.json"))
    manifest = _read(os.path.join(out, "manifest.json"))
    status = {"ok": False, "reasons": [], "files": [], "dest": ""}

    if not gate or not gate.get("printable"):
        status["reasons"].append("print gate is not printable; release refused")
        return status
    if gate.get("design_hash") != digest:
        status["reasons"].append("gate result is from a different design; rerun the gate")
        return status
    if not manifest:
        status["reasons"].append("no .out/manifest.json; run build.py")
        return status

    sources = {}
    for part in manifest.get("parts", []):
        for key in ("step", "3mf", "stl"):
            if part.get(key):
                sources[os.path.abspath(part[key])] = None
    if manifest.get("fcstd"):
        sources[os.path.abspath(manifest["fcstd"])] = None
    for name in ("report.json", "print_gate.json"):
        path = os.path.join(out, name)
        if os.path.exists(path):
            sources[path] = None
    missing = [p for p in sources if not os.path.exists(p)]
    if missing:
        status["reasons"].append("missing export files: " + ", ".join(missing))
        return status

    dest = os.path.join(os.path.dirname(os.path.abspath(project)), "print", _stem(params))
    os.makedirs(dest, exist_ok=True)
    for src in sources:
        target = os.path.join(dest, os.path.basename(src))
        shutil.copy2(src, target)
        status["files"].append({"name": os.path.basename(target),
                                "source": src, "sha256": _sha(target)})

    date = time.strftime("%Y-%m-%d")
    with open(os.path.join(dest, "README.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(_readme(params, gate, digest, status["files"], date))
    release_record = {
        "released": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "design_hash": digest,
        "stem": _stem(params),
        "gate": {"printable": True, "checks": gate.get("checks", {})},
        "files": status["files"],
    }
    with open(os.path.join(dest, "release.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(release_record, f, indent=2)
    status.update(ok=True, dest=dest)
    return status


def main():
    project = os.environ.get("FCP_PROJECT") or os.getcwd()
    status = release(project)
    status["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = os.path.join(project, ".out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "release_status.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(status, f, indent=2)
    print("RELEASE", "OK" if status["ok"] else "REFUSED")
    for reason in status["reasons"]:
        print("  - " + reason)
    if status["ok"]:
        print("  " + status["dest"])
    sys.stdout.flush()
    sys.exit(0 if status["ok"] else 1)


if not os.environ.get("FCP_NO_MAIN"):
    main()  # FreeCADCmd does not set __name__ == "__main__"
