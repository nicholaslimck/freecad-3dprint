---
name: freecad-3dprint
description: Design 3D-printable parts as parametric FreeCAD Python scripts on Windows, run headless through FreeCADCmd, with automatic printability checks (validity, watertightness, wall thickness, overhangs, bed contact), orthographic renders and optional slicer CLI verification. Use this skill whenever the user wants to design, model, CAD, modify or fix a part for 3D printing, mentions FreeCAD, STL/3MF/STEP output, brackets, enclosures, mounts, adapters, cases, jigs or replacement parts, or asks an agent to "make a printable" anything, even if they don't mention FreeCAD by name.
---

# FreeCAD 3D-print design workflow

You design parts by writing a parametric Python build script that FreeCAD runs
headless. You never drive the GUI. You see your work through three channels:
`out/report.json` (numbers), `out/views/*_sheet.png` (pictures) and, optionally,
`out/slice_report.json` (what the slicer thinks). A part is finished only when all
three agree with the spec.

The bundled kit does the plumbing. Your job is the spec and the geometry functions.

## Kit contents (in this skill's `kit/` folder)
```
build.py            parametric build script: you edit the feature functions
params.json         every dimension and print setting; the single source of truth
spec.md             requirements template, filled in with the user before modelling
fcp/cadlib.py       helpers: rounded_box, hole, counterbore, countersink, teardrop_hole,
                    safe_fillet, chamfer_bed_edges, print_oriented, export_all ...
fcp/check_print.py  printability checks  -> out/report.json
fcp/render_views.py 6 orthographic views + contact sheet -> out/views/
fcp/slice.py        PrusaSlicer (or custom) CLI wrapper -> out/slice_report.json
fcp/doctor.py       environment check
fcp/run.ps1         runs the pipeline; exit code 0 = everything passed
```
References, read when needed:
- `references/freecad-api.md`: the FreeCAD calls known to work, gotchas, and an error-message table. **Read it before writing geometry code.**
- `references/printability.md`: wall, fit, fastener and overhang numbers. Read it while writing the spec.

## Phase 0: Set up the project (once per part)
1. Create a project folder (ask the user where if it isn't obvious), copy everything from `kit/` into it, and `git init` it if git is available.
2. Run the doctor: `powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step doctor`.
   - If FreeCADCmd isn't found, ask the user for the path and set `$env:FREECAD_CMD`.
   - numpy and matplotlib ship with FreeCAD on Windows. If either is missing, renders won't work. Say so and carry on with report-only checks.
3. **Without PowerShell** (bash, WSL, another harness), run the same steps directly from the project folder with `FCP_PROJECT` set to it:
   ```
   FreeCADCmd.exe build.py
   FreeCADCmd.exe fcp/check_print.py
   FreeCADCmd.exe fcp/render_views.py
   FreeCADCmd.exe fcp/slice.py          # optional
   ```
   From WSL, call the Windows exe by its `/mnt/c/...` path and pass Windows-style paths (`wslpath -w`).
   FreeCADCmd's exit code isn't reliable, so always read the `out/*.json` status files.

## Phase 1: Write the spec (gate: user confirms)
Fill in `spec.md` and `params.json` with the user before writing any geometry.
Most bad parts come from guessed dimensions, not from bad code.

- Ask for **measured** values of everything the part mates with: screw sizes, board dimensions, hole spacing, tube diameters. If the user has a datasheet, drawing or photo with a ruler, use it. Never invent a mating dimension. Mark it as an open question and ask.
- Get printer, nozzle, material, and whether supports are acceptable. Pick fits and clearances from `references/printability.md` and write down which rule each came from.
- Decide the print orientation with the user, based on load direction and layer-line weakness. Record it as `print.rotate` steps.
- Fill in `checks.bbox_mm` with the expected overall size so mistakes in scale or axis are caught automatically.
- Present a short summary: what it is, key dimensions, fits, orientation, and anything left out of scope. **Wait for confirmation.** When there's a real design choice (orientation, how it fastens, one piece vs two), lay out the options and recommend one rather than silently picking.

## Phase 2: Write the geometry
Edit `build.py`. The example plate shows the pattern.
- **All numbers come from `params.json`.** A literal dimension in build.py is a bug. Small epsilons from cadlib are the only exception.
- **One function per feature**, applied in order in `build()`. A later change then touches one function.
- Model in "design orientation", with whatever axes are natural. Print orientation is applied only at export and check time.
- Build from primitives, extruded polygons and booleans (see the API reference). Avoid Sketcher and PartDesign from scripts.
- Fillet and chamfer last, or select edges after the booleans that affect them. Use `safe_fillet`, and check `build_status.json` warnings for fillets that were skipped.
- Use print-aware features: `teardrop_hole` for horizontal holes, chamfers rather than fillets on downward edges, and `chamfer_bed_edges` for elephant foot.
- For multi-part designs, `build()` returns `{"name": shape, ...}`. Model mating parts from the same params so they stay in sync, and check clearance between them with `a.distToShape(b)` in a feature function, recording the result in a warning.
- When unsure whether an API call exists, run a tiny probe script first.

## Phase 3: Build, check, look, fix (the loop)
Run `fcp\run.ps1` (build, check, render). After every run:
1. Read `out/build_status.json`. If it's `ok: false`, fix using the traceback and the error table in the API reference.
2. Read `out/report.json`. Every **error** must be fixed. Every **warning** must be fixed, or justified in the hand-off with a reason the user would accept. **Info** items go in the hand-off.
3. **Look at `out/views/<part>_sheet.png`.** Compare it to the spec feature by feature: is each hole on the right face, the right count, the right side, not mirrored? Red regions are unsupported overhangs. If you can't view images in this harness, say so and ask the user to open the sheet or the `.FCStd` before you call the part done.
4. Commit after each run that passes (`git commit -am "<what changed>"`).

Rules for the loop:
- **Don't change the checks to make them pass.** Don't edit `fcp/*`, or loosen `min_wall`, `max_overhang_deg`, `checks.bbox_mm` and so on, without telling the user why the original value was wrong and getting agreement. Record any agreed change in spec.md.
- If the same error survives three attempts, stop. Explain what you tried and ask the user. Don't thrash.
- The wall-thickness scan samples points, so it can miss tiny features. The overhang check doesn't know about bridges. That's why the renders exist.

## Phase 4: Slice (optional but recommended)
Do this when the user has a slicer. Ask them to export their printer profile once (PrusaSlicer: File > Export > Export Config) and set `slicer.config` and, if needed, `slicer.exe` in params.json. Then run `fcp\run.ps1 -Slice`.
Read `slice_report.json`: print time, filament, and any warnings (empty layers, objects outside the bed, support generated when `supports_allowed` is false). For OrcaSlicer or Bambu Studio, use `"type": "custom"` with the argument template described in `fcp/slice.py`. Verify the flags with the user's slicer `--help` first.

## Phase 5: Hand off
Give the user a short summary:
- Where the outputs are: `out/<name>.FCStd` (open in FreeCAD), `.step`, and `_print.3mf/.stl` (already in print orientation).
- The key parameters and how to change them (edit `params.json`, rerun `run.ps1`).
- Report status, any warnings you justified, and info items.
- Slicer stats if sliced.
- **What to test-print first** when fits matter: suggest a small coupon of the critical feature, such as a hole at nominal +0.1/+0.2/+0.3. Ask the user to report back the measurements so they can go into params.json.

## Later changes
For a dimension change, edit params.json and rerun the pipeline. For a new feature, add a function, call it in `build()`, and rerun. Update spec.md whenever the requirements change, so the spec, params and geometry never disagree.
