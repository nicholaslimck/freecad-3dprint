"""Hash of the design-relevant params, shared by the checks and the renders.

Stdlib only, so `mcp_probe` can use it without pulling in numpy or FreeCAD.
"""
import copy
import hashlib
import json


def design_hash(params):
    """Hash of the design-relevant params.

    Triage records (checks.accept) and the manual preview record are excluded:
    accepting a warning or recording a slicer check must not make outputs stale.
    """
    p = copy.deepcopy(params)
    (p.get("print") or {}).pop("preview", None)
    (p.get("checks") or {}).pop("accept", None)
    blob = json.dumps(p, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
