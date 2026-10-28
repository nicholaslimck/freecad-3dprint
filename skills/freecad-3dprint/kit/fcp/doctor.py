"""Environment check. Run with:  FreeCADCmd.exe fcp\\doctor.py   (run.ps1 -Step doctor)

Writes .out/doctor.json. Problems (FreeCAD missing, UTF-8 BOM in a project .py,
unreadable params.json) make the check fail; missing numpy/matplotlib only warns,
because report-only checks still work.

A UTF-8 BOM makes FreeCADCmd fail with "Unexpected UTF-8 BOM". PowerShell's
`Set-Content -Encoding UTF8` writes one on Windows PowerShell 5.1.
"""
import json
import os
import sys

PROJECT = os.environ.get("FCP_PROJECT") or os.getcwd()
SKIP_DIRS = {".git", ".out", "out", "__pycache__", ".venv", "venv", "node_modules", "archive"}


def bom_files(root):
    bad = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "rb") as f:
                    if f.read(3) == b"\xef\xbb\xbf":
                        bad.append(os.path.relpath(path, root))
            except OSError:
                continue
    return sorted(bad)


def nested_workspace(project):
    """The enclosing .freecad-3dprint directory, if this workspace is nested inside one."""
    current = os.path.dirname(os.path.abspath(project))
    while True:
        if os.path.basename(current) == ".freecad-3dprint":
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return ""
        current = parent


def main():
    result = {"ok": True, "problems": [], "warnings": [], "python": sys.version.split()[0]}
    print("python", sys.version.split()[0], sys.executable)

    try:
        import FreeCAD as App
        result["freecad"] = ".".join(App.Version()[:3])
        print("FreeCAD", result["freecad"])
    except Exception as exc:  # noqa: BLE001
        result["problems"].append("FreeCAD import failed: %s" % exc)
        print("FreeCAD import FAILED:", exc)

    import importlib
    for mod in ("Part", "Mesh", "MeshPart", "numpy", "matplotlib"):
        try:
            importlib.import_module(mod)
            print("ok  ", mod)
        except Exception as exc:  # noqa: BLE001
            result["warnings"].append("%s missing: %s" % (mod, exc))
            print("MISSING", mod, "-", exc)

    bad = bom_files(PROJECT)
    if bad:
        result["problems"].append(
            "UTF-8 BOM in %s: FreeCADCmd fails with 'Unexpected UTF-8 BOM'. "
            "Rewrite the file without a BOM (Python: open(p, 'w', encoding='utf-8'))." % ", ".join(bad))
        print("BOM ", ", ".join(bad))

    nested = nested_workspace(PROJECT)
    if nested:
        result["problems"].append(
            "workspace is nested inside another .freecad-3dprint at %s; use one workspace per "
            "project and run from the outer one" % nested)
        print("NESTED", nested)

    try:
        with open(os.path.join(PROJECT, "params.json"), encoding="utf-8") as f:
            params = json.load(f)
        result["name"] = params.get("name")
        print("params.json ok:", params.get("name"))
    except Exception as exc:  # noqa: BLE001
        result["problems"].append("params.json unreadable: %s" % exc)
        print("params.json FAILED:", exc)

    result["ok"] = not result["problems"]
    print("FCP_PROJECT =", PROJECT)
    print("FCP_SLICER  =", os.environ.get("FCP_SLICER", "(unset)"))
    os.makedirs(os.path.join(PROJECT, ".out"), exist_ok=True)
    with open(os.path.join(PROJECT, ".out", "doctor.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, indent=2)
    print("DOCTOR", "OK" if result["ok"] else "FAILED")
    for p in result["problems"]:
        print("  - " + p)
    sys.stdout.flush()
    sys.exit(0 if result["ok"] else 1)


if not os.environ.get("FCP_NO_MAIN"):
    main()  # FreeCADCmd does not set __name__ == "__main__"



