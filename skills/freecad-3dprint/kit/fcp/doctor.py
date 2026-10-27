"""Environment check. Run with:  FreeCADCmd.exe fcp\\doctor.py   (run.ps1 -Step doctor)"""
import importlib
import os
import sys

print("python", sys.version.split()[0], sys.executable)
try:
    import FreeCAD as App
    print("FreeCAD", ".".join(App.Version()[:3]))
except Exception as exc:  # noqa: BLE001
    print("FreeCAD import FAILED:", exc)
for mod in ("Part", "Mesh", "MeshPart", "numpy", "matplotlib"):
    try:
        importlib.import_module(mod)
        print("ok  ", mod)
    except Exception as exc:  # noqa: BLE001
        print("MISSING", mod, "-", exc)
print("FCP_PROJECT =", os.environ.get("FCP_PROJECT") or os.getcwd())
print("FCP_SLICER  =", os.environ.get("FCP_SLICER", "(unset)"))
