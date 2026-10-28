"""Slice each part with a real slicer and summarise the result.

Run with:  FreeCADCmd.exe fcp\\slice.py   (or any Python 3; no FreeCAD imports)

params.json "slicer":
  type   "prusa" (PrusaSlicer console) or "custom"
  exe    path to the slicer CLI; blank = env FCP_SLICER, then common install paths
  config printer/print/filament profile exported from the slicer GUI
         (PrusaSlicer: File > Export > Export Config -> .ini)
  args   extra CLI args. For "custom" this is the WHOLE command after the exe, with
         placeholders {model} {gcode} {outdir} {config}. Example for OrcaSlicer
         (verify flags with `orca-slicer.exe --help` on your version):
         ["--slice", "0", "--load-settings", "{config}", "--outputdir", "{outdir}", "{model}"]

Writes .out/slice_report.json.
"""
import glob
import json
import os
import re
import subprocess
import time

PROJECT = os.environ.get("FCP_PROJECT") or os.getcwd()
OUT = os.path.join(PROJECT, ".out")

PRUSA_GUESSES = [
    r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
    r"C:\Program Files\PrusaSlicer\prusa-slicer-console.exe",
]

STAT_PATTERNS = {
    "print_time": r";\s*estimated printing time \(normal mode\)\s*=\s*(.+)",
    "filament_g": r";\s*(?:total )?filament used \[g\]\s*=\s*([\d.]+)",
    "filament_mm": r";\s*filament used \[mm\]\s*=\s*([\d.]+)",
    "support_material": r";\s*support_material\s*=\s*(\d)",
    "layer_height": r";\s*layer_height\s*=\s*([\d.]+)",
}


def find_exe(cfg):
    for cand in [cfg.get("exe"), os.environ.get("FCP_SLICER")]:
        if cand and os.path.exists(cand):
            return cand
    if cfg.get("type", "prusa") == "prusa":
        for g in PRUSA_GUESSES:
            hits = glob.glob(g)
            if hits:
                return hits[0]
    raise FileNotFoundError("slicer executable not found; set slicer.exe in params.json or FCP_SLICER")


def gcode_stats(path):
    stats = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    blob = "".join(lines[:400] + lines[-1500:])  # stats live in header/footer
    for key, pat in STAT_PATTERNS.items():
        m = re.search(pat, blob)
        if m:
            stats[key] = m.group(1).strip()
    return stats


def fill(arg, subs):
    """Replace {model}/{gcode}/{outdir}/{config}; other braces are left alone."""
    for k, v in subs.items():
        arg = arg.replace("{%s}" % k, v)
    return arg


def fresh_gcode(expected, outdir, t0):
    """The expected G-code, else the newest one written since t0 (custom slicers may pick their own name)."""
    if os.path.exists(expected):
        return expected
    newest = sorted((p for p in glob.glob(os.path.join(outdir, "*.gcode")) if os.path.getmtime(p) >= t0),
                    key=os.path.getmtime)
    return newest[-1] if newest else None


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def update_manifest(report):
    """Record what was sliced in .out/manifest.json so the gate can spot a stale file."""
    path = os.path.join(OUT, "manifest.json")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    parts = {p.get("name"): p for p in manifest.get("parts", [])}
    for part in report.get("parts", []):
        rec = parts.get(part.get("name"))
        if rec is None:
            continue
        rec["slicer"] = {"ok": part.get("returncode") == 0 and bool(part.get("gcode")),
                         "gcode": part.get("gcode"),
                         "model_sha256": part.get("model_sha256"),
                         "stats": part.get("stats", {}),
                         "warnings": part.get("warnings", [])}
    manifest["sliced"] = report.get("ok", False)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)


def main():
    with open(os.path.join(PROJECT, "params.json"), encoding="utf-8") as f:
        P = json.load(f)
    with open(os.path.join(OUT, "build_status.json"), encoding="utf-8") as f:
        status = json.load(f)
    cfg = P.get("slicer", {})
    report = {"ok": False, "parts": []}
    try:
        exe = find_exe(cfg)
        config = cfg.get("config", "")
        if config and not os.path.isabs(config):
            config = os.path.join(PROJECT, config)
        no_support = not P.get("print", {}).get("supports_allowed")
        for rec in status["parts"]:
            model = rec.get("3mf") or rec["stl"]
            gcode = os.path.join(OUT, (rec.get("stem") or rec["name"]) + ".gcode")
            subs = {"model": model, "gcode": gcode, "outdir": OUT, "config": config}
            if cfg.get("type", "prusa") == "prusa":
                cmd = [exe, "--export-gcode", "--output", gcode]
                if config:
                    cmd += ["--load", config]
                cmd += [fill(a, subs) for a in cfg.get("args", [])] + [model]
            else:
                cmd = [exe] + [fill(a, subs) for a in cfg.get("args", [])]
            prusa = cfg.get("type", "prusa") == "prusa"
            if no_support and prusa:
                cmd.insert(1, "--support-material=0")  # supports must not creep in from the profile
            if os.path.exists(gcode):
                os.remove(gcode)  # never read a previous run's output
            t0 = time.time() - 1  # slack for coarse file timestamps
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            support_override = ""
            if proc.returncode != 0 and no_support and prusa and "--support-material=0" in cmd:
                # Older/newer CLI builds may not take the override; retry and say so.
                cmd = [c for c in cmd if c != "--support-material=0"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
                support_override = ("this slicer rejected --support-material=0; check supports in "
                                    "the preview and record print.preview")
            log = (proc.stdout or "") + (proc.stderr or "")
            part = {"name": rec["name"], "cmd": cmd, "returncode": proc.returncode,
                    "model": model, "model_sha256": sha256(model),
                    "warnings": [l.strip() for l in log.splitlines()
                                 if re.search(r"warn|error|empty|outside|support", l, re.I)][:30]}
            if support_override:
                part["support_override"] = support_override
                part["warnings"].insert(0, support_override)
            gcode = fresh_gcode(gcode, OUT, t0)
            if gcode and proc.returncode == 0:
                part["gcode"] = gcode
                part["stats"] = gcode_stats(gcode)
                if no_support and part["stats"].get("support_material") == "1":
                    part["warnings"].insert(0, "slicer generated support but print.supports_allowed is false")
            else:
                part["log_tail"] = log[-3000:]
            report["parts"].append(part)
        report["ok"] = all(p["returncode"] == 0 and p.get("gcode") for p in report["parts"])
        if not config:
            report["note"] = "no slicer.config set: sliced with slicer defaults, not your printer profile"
    except Exception as exc:  # noqa: BLE001
        report["error"] = repr(exc)
    with open(os.path.join(OUT, "slice_report.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2)
    update_manifest(report)
    print("SLICE", "OK" if report["ok"] else "FAILED")
    for p in report["parts"]:
        print("  %s: %s" % (p["name"], p.get("stats") or p.get("log_tail", "")[-500:]))
        for w in p["warnings"]:
            print("    ! " + w)
    if "error" in report:
        print(report["error"])
    if "note" in report:
        print("  note: " + report["note"])


if not os.environ.get("FCP_NO_MAIN"):
    main()
