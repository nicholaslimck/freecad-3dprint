---
name: freecad-3dprint
description: Design 3D-printable parts as parametric FreeCAD Python scripts on Windows, run headless through FreeCADCmd, with automatic printability checks (validity, watertightness, wall thickness, overhang/support classification, connectivity, fit relations), orthographic and detail renders, and a print gate that requires a slicer or recorded supports-off preview. Use this skill whenever the user wants to design, model, CAD, modify or fix a part for 3D printing, mentions FreeCAD, STL/3MF/STEP output, brackets, enclosures, mounts, adapters, cases, jigs or replacement parts, or asks an agent to "make a printable" anything, even if they don't mention FreeCAD by name.
---

# FreeCAD 3D-print design workflow

You design parts by writing a parametric Python build script that FreeCAD runs
headless. You never drive the GUI. You see your work through four channels:

- `.out/report.json` - checks, each finding has a stable `code`
- `.out/views/*_sheet.png` - contact sheet, plus a detail/section sheet per feature
- `.out/slice_report.json` - what the slicer thinks (when a slicer is configured)
- `.out/print_gate.json` - the only file that may say `printable: true`

**`report.json` passing is not a print guarantee.** A part is finished only when
the print gate says printable, which needs a clean slice or a recorded manual
supports-off preview.

## Kit contents (in this skill's `kit/` folder)
```
build.py            parametric build script: you edit the feature functions and build(params)
params.json         every dimension, check expectation, coupon and print setting
spec.md             requirements template, filled in with the user before modelling
fcp/cadlib.py       helpers: rounded_box, hole, counterbore, countersink, teardrop_hole,
                    safe_fillet, chamfer_bed_edges, print_oriented, section, add_coupons,
                    export_all (writes .out/manifest.json), write_text ...
fcp/analysis.py     pure-numpy mesh analysis: down-face regions, bridge/cantilever/support
fcp/fit.py          checks.fit: does the board/phone/module an enclosure is for fit inside it?
fcp/design_hash.py  hash of the design-relevant params (stdlib only)
fcp/cli.py          run(main, module_name=__name__): runs a script's main only when
                    FreeCAD executed it, never on import
fcp/check_print.py  checks -> .out/report.json (codes, metrics, relations, coupons)
fcp/render_lines.py TechDraw line art: the six shape views + one contact sheet -> .out/views/
fcp/render_views.py the raster support map (bottom view only), red/amber categories
fcp/mcp_probe.py    is the optional FreeCAD MCP server up? -> .out/doctor.json (information only)
fcp/slice.py        PrusaSlicer (or custom) CLI wrapper -> .out/slice_report.json
fcp/gate.py         print gate -> .out/print_gate.json
fcp/release.py      verified design -> <project>/print/<stem>/
fcp/status.py       current version, gate state, exact file -> .out/status.json
fcp/doctor.py       environment, BOM and params check -> .out/doctor.json
fcp/run.ps1         build -> check -> render (-> slice) -> gate; exit 0 = printable
```
References, read when needed:
- `references/freecad-api.md`: FreeCAD calls known to work, gotchas, error table. **Read it before writing geometry code.**
- `references/printability.md`: wall, fit, fastener, overhang numbers. Read it while writing the spec.
- `references/latches-and-snaps.md`: **read before designing any lid, latch, catch or snap fit.**

## Phase 0: Set up the workspace (once per part)
1. Ask where the project folder is (the folder the part belongs to). Create
   `<project>/.freecad-3dprint/`, copy everything from `kit/` into it (including
   `kit/.gitignore`), and `git init` the workspace if git is available and the
   parent is not already a repository. Everything below runs with that workspace
   as the working directory, so `fcp\...`, `build.py` and `.out/...` are relative
   to it. If you must run from the parent folder, prefix paths with
   `.freecad-3dprint\`. The `.gitignore` ignores `.out/`; commit `spec.md`,
   `params.json` and `build.py`, not the generated files. Never create a second
   workspace inside an existing one; the doctor fails a nested workspace.
2. Run the doctor: `powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step doctor`.
   - It fails on a UTF-8 BOM, unreadable params.json or missing FreeCADCmd. If FreeCADCmd isn't found, ask for the path and set `$env:FREECAD_CMD`.
   - numpy and matplotlib ship with FreeCAD on Windows. If either is missing, renders won't work: say so and carry on with report-only checks.
3. **Without PowerShell** (bash, WSL, another harness), run the steps directly from the workspace with `FCP_PROJECT` set to its path:
   ```
   FreeCADCmd.exe build.py
   FreeCADCmd.exe fcp/check_print.py
   FreeCADCmd.exe fcp/render_views.py
   FreeCADCmd.exe fcp/slice.py          # optional
   FreeCADCmd.exe fcp/gate.py
   ```
   `fcp/render_views.py` now renders **both** engines: TechDraw line art for shape and the raster support map. FreeCADCmd's exit code isn't reliable, so read `.out/*.json`. Every kit script ends with `run(main, module_name=__name__)`, which is what makes `main()` actually run under FreeCADCmd; a bare `if __name__ == "__main__":` never fires there. From WSL, call the Windows exe by its `/mnt/c/...` path and pass Windows-style paths (`wslpath -w`).
4. **Optional:** run `python fcp\mcp_probe.py`. If `available` is false, mention `references/mcp-setup.md` **once** and carry on either way; MCP is never required. If it is true, the user has a live FreeCAD you can use in Phase 2.

## Phase 1: Write the spec (gate: user confirms)
Fill in `spec.md` and `params.json` with the user before writing geometry. Most bad
parts come from guessed dimensions, not from bad code.

- Ask for **measured** values of everything the part mates with: screw sizes, board dimensions, hole spacing, tube diameters. Never invent a mating dimension; mark it as an open question.
- Get printer, nozzle, material and whether supports are acceptable. Pick fits and clearances from `references/printability.md` and record which rule each came from.
- Decide the print orientation with the user. Record it as `print.rotate`, and say which faces become down faces after the flip.
- If there is a latch, catch, lid or snap: fill in the decision table in `spec.md` using `latches-and-snaps.md` **before** modelling. For a one-piece, support-free, lid-mounted 90 deg catch, say plainly that the retention face becomes an unsupported shelf and offer the alternatives.
- Fill in `checks.bbox_mm` per part (`{"<part>": [x, y, z]}`) so scale and axis mistakes are caught. A fillet can inflate the OCC bbox: measure the built part.
- **If the part holds something** (a case, tray, holder, or a lid that must close over a connector), declare the occupant in `checks.fit` now, with its measured box and the height of whatever stands on top of it. Nothing else in the kit can see a foreign body: a case can pass every check and still be too shallow, and the report will say so only if you asked it to. See `freecad-api.md` §13.
- Plan the coupon now if a fit, flex or snap matters: source part + `coupon.section_mm`, real orientation, pass/fail criteria.
- Present a short summary: what it is, key dimensions, fits, orientation, whether supports are allowed, what a coupon will test, and anything out of scope. **Wait for confirmation.**

## Phase 2: Write the geometry
Edit `build.py`. One `build(params)` function that returns a shape or `{part_name: shape}`.

- **All numbers come from `params.json`.** A literal dimension in build.py is a bug. Small epsilons from cadlib are the only exception.
- **One function per feature**, called in order in `build(params)`. Never keep a second copy of the feature code for the FCStd, a coupon or an "editable" script. Coupons are cut from the real part with `add_coupons(parts, P, build, WARN)`; the FCStd is exported from the same shapes.
- Model in "design orientation", with whatever axes are natural. Print orientation is applied only at export and check time.
- Build from primitives, extruded polygons and booleans (see the API reference). Avoid Sketcher and PartDesign from scripts.
- **Show options, don't describe them.** When there are 2+ candidate shapes (latch, hinge, loop, bezel), build each one and render it before asking the user to choose. Text-only options are not a design review; the user is judging geometry they cannot see.
- **Live review over MCP (only when the user asks to see options).** If `mcp_probe.py` reports the server available *and* the user says "show me", "let me look" or asks for mockups, build each candidate in a **scratch document** named `scratch_<feature>_<candidate>` and tell the user it is disposable and should be closed. Never build candidates in the user's workspace document: a save there changes the `.py` files `gate.py` hashes and muddies the release path. Without MCP, or without the user asking, the render-each-candidate rule above stands unchanged.
- **Starting from an existing model.** A STEP can be loaded with `Part.read()` and used as a reference or a boolean body. An STL/3MF is a triangle mesh, not an editable B-rep: measure it, record the dimensions in `spec.md`, and rebuild the part parametrically; use the mesh only as a visual or subtractive reference (`Mesh.Mesh(path)`, `MeshPart`). See `freecad-api.md`.
- Fillet and chamfer last, or select edges after the booleans that affect them. Use `safe_fillet`, and check `build_status.json` warnings for fillets that were skipped.
- Use print-aware features: `teardrop_hole` for horizontal holes, chamfers rather than fillets on downward edges, `chamfer_bed_edges` for elephant foot.
- For multi-part designs, model all parts from the same params. Declare `checks.relations` for clearance/engagement between named parts (see below) instead of measuring by hand.
- When unsure whether an API call exists, run a tiny probe script first.

## Phase 3: Build, check, look, fix (the loop)
Run `fcp\run.ps1` (build, check, render, gate). After every run:
1. Read `.out/build_status.json`. If `ok: false`, fix using the traceback and the error table.
2. Read `.out/report.json`. **Every error must be fixed.** Every warning must be accepted in `params.checks.accept` with a reason and evidence, or fixed. Info goes in the hand-off.
3. **Look at `.out/views/<stem>_sheet.png`.** It has two kinds of panel, and the footer names which is which:
   - **Shape panels (iso, front, right, top, back_iso) are TechDraw line art**: exact, hidden lines removed, no colour. Judge occlusion, the hinge seam, the lip groove and the latch loop from these. A gap smaller than a pixel in the whole-part view is what `render.features` close-ups are for.
   - **The bottom panel is the support map**: a flat raster classification, not a shape view. Red = steep overhang, amber = flat down face classified as cantilever/unsupported. This is the only panel where colour means something, so never read a support problem off a shape panel.
   Compare the sheet to the spec feature by feature. If `render.features` is set, look at those close-ups as well: each feature gets line art plus a support panel, and with a `section` it also gets a sectioned variant. The whole-part sheet is too small for a latch. Feature `bbox_mm` values are in print orientation (after `print.rotate`), not design coordinates.
4. Commit after each run that passes.

Read the finding codes before touching anything:

| Code | Meaning | Usual fix |
|---|---|---|
| `components_unexpected` | wrong number of solids; `components` lists volume and bbox of each | the feature is not attached, or declare `checks.expected_solids` for an intentional multi-solid part |
| `root_disconnected` | a declared `inside_points` entry is not inside the part | move the root until it merges into the parent |
| `flat_cantilever` | flat down face anchored on one side only | redesign, accept with evidence, or add support |
| `flat_unsupported` | flat down face with nothing below and no anchor | same |
| `declared_bridge_is_cantilever` | accepted as a bridge, geometry says one-ended | **error:** the bridge claim is false; fix the geometry |
| `flat_bridge` | flat down face anchored at both ends | accept with code `flat_bridge` and evidence if intentional |
| `relation_failed` | measured clearance/interference outside the declared range | fix the fit; the values are in `report.relations` |
| `fit_collision` | the declared occupant overlaps the part, or has too little headroom | fix the cavity or the standoffs; the values are in `report.fit` |
| `coupon_not_section` | coupon is not cut from the real part | set `coupon.source` + `coupon.section_mm` |
| `wall_thin`, `overhang_steep`, `bbox_mismatch`, `mesh_*` | as before | fix the geometry |

Rules for the loop:
- **Don't change the checks to make them pass.** Don't edit `fcp/*`, or loosen `min_wall`, `max_overhang_deg`, `checks.bbox_mm` and so on, without telling the user why the original value was wrong and getting agreement. Record any agreed change in spec.md.
- Accepting a warning means adding to `params.checks.accept`:
  ```json
  {"code": "flat_bridge", "region_center_mm": [12.0, 0.0, 8.0],
   "reason": "living-hinge strap, supports at both towers",
   "evidence": "report shows anchors at both ends; coupon printed clean",
   "accepted_by": "user", "date": "2026-10-28"}
  ```
  A warning without evidence does not satisfy the gate. A regional warning (`flat_*`, `overhang_steep`) needs `region_center_mm`; a part-wide warning (`small_bed_contact`, `tall_thin`, `open_shell`, coupon findings) must omit it. Never accept a warning by writing "it is a bridge" without anchor evidence in the report.
- If the same error survives three attempts, stop. Explain what you tried and ask the user. Don't thrash.

## Phase 4: Slice and gate (mandatory before calling it done)
- With a slicer: ask the user to export their printer profile once (PrusaSlicer: File > Export > Export Config), set `slicer.config` and, if needed, `slicer.exe`, then run `fcp\run.ps1 -Slice`. The wrapper forces `--support-material=0` for PrusaSlicer when supports are not allowed and records the model hash in the manifest.
- Without a slicer: open the part in the user's slicer with supports off and look at the layer preview. Record it in `params.json`:
  ```json
  "print": {"preview": {"done": true, "supports_off": true, "by": "user",
             "date": "2026-10-28", "evidence": "layers 40-52 show the latch shelf supported by the tab"}}
  ```
  and note the same in `spec.md`. Do not claim printable without one of the two.
- Read `.out/slice_report.json` for print time, filament, support generation, out-of-bed and empty-layer warnings.
- Read `.out/print_gate.json`. `printable: false` lists exactly what is missing (untriaged warning, stale outputs, no slice/preview). `run.ps1` exits nonzero until it passes.
- If the slicer shows an unsupported region the checks missed, treat it as a check bug: say so, fix the geometry first, then add the case to the triage table.
- **Deliberate experiment.** If the user wants to print something the gate has not verified, accept the warnings with `"reason": "experiment"` and `"evidence": "not print-verified; experimental print"`, say plainly that the gate is still unsatisfied, and do **not** run `-Step release`. The print is allowed; the claim of printable is not.

## Phase 5: Hand off
Give the user a short summary:
- Run `fcp\run.ps1 -Step status` first and quote its `NEXT`/`SLICE`/`RELEASE` lines. If the user asks "where is the current version?", that command is the answer; do not hunt through `.out`.
- Where the workspace is: `<project>/.freecad-3dprint/`, and the released bundle in
  `<project>/print/<stem>/`.
- Once the gate passes, run `fcp\run.ps1 -Step release`. It refuses unless the gate is
  printable for the current design, then copies the slice target, STEP, FCStd, report,
  gate and manifest into `print/<stem>/` with a README and `release.json` (hashes).
  Commit `print/` and the workspace sources (`spec.md`, `params.json`, `build.py`);
  `.out/` is ignored by the kit's `.gitignore`.
- The exact file to print or slice: the `slice_this` file, now also present in
  `print/<stem>/` (name it, do not say "the 3MF"). The FCStd there opens in FreeCAD.
- The key parameters and how to change them (edit `params.json`, rerun `run.ps1`); `version` in params bumps the output names so old files cannot be mistaken for new.
- Gate status: printable or not, with the reason. Report any accepted warnings with their evidence, and info items.
- Slicer stats if sliced, and whether the preview was manual.
- **What to test-print first** when fits or flex matter: a coupon cut from the real feature (`params.coupon`), printed in the real orientation. Ask for measurements and open/close results, and put them in spec.md and params.json.

## Later changes
For a dimension change, edit `params.json`, bump `version`, rerun, and release. For a
new feature, add a function, call it in `build(params)`, and rerun. Update `spec.md`
when the requirements change. If the user edits the generated `<stem>.FCStd` by hand,
treat their file as a reference: import it (`Part.read` for STEP/FCStd), compare the
bbox/volume with the built part, and port the change back into `params.json` and
`build.py`. Never maintain the generated file and a hand-edited copy in parallel.
Old working files: `fcp\run.ps1 -Step clean` archives `.out\` to
`.out\archive\<timestamp>\`; released folders under `print/` are never touched.
