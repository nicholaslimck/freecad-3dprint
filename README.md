# freecad-3dprint

An agent skill for designing 3D-printable parts in FreeCAD on Windows. The agent writes a parametric Python script, FreeCAD runs it headless, and a set of checks reports whether the part will print. The agent never touches the FreeCAD GUI. It reads a JSON report, looks at rendered views of the part, and can slice the part with your own printer profile before it calls the job done.

It works with Claude Code as a plugin, and with any other agent that can read a markdown file and run commands on a Windows machine.

## How it works

The agent follows five steps, which are written out in [`SKILL.md`](skills/freecad-3dprint/SKILL.md).

1. It agrees a spec with you first: measured dimensions of everything the part mates with, fits, material, print orientation, and whether supports are acceptable. It won't start modelling until you confirm.
2. It puts every dimension in `params.json` and writes one Python function per feature in `build.py`.
3. It runs the pipeline, reads `out/report.json`, looks at the rendered views, and fixes what's wrong. It may not loosen a check to make it pass without your agreement, and it stops to ask after three failed attempts at the same error.
4. If you have PrusaSlicer (or another slicer with a CLI), it slices the part and reads back print time, filament and warnings.
5. It hands over the FreeCAD file, a STEP, and a print-oriented 3MF/STL, along with a summary and a suggestion for what to test-print first.

The checks in `report.json` cover:

- shape validity and solid count
- the expected bounding box, which catches scale and axis mistakes
- whether the mesh is watertight and manifold
- walls thinner than `print.min_wall`
- overhangs steeper than `print.max_overhang_deg`
- flat downward faces (bridges)
- bed contact area and tall, thin parts
- whether the part fits the build volume
- horizontal holes that would print better as teardrops

The renders are a six-view contact sheet in print orientation, with overhangs shaded red.

## Requirements

- Windows with FreeCAD installed. It's written for FreeCAD 1.0 or later; earlier versions haven't been tried. FreeCAD's bundled Python already includes numpy and matplotlib, which the checks and renders need.
- PowerShell for the `run.ps1` runner. Without it, you can call `FreeCADCmd.exe` directly (see below).
- Optional: PrusaSlicer for the slicing step. Other slicers work through a custom argument template in `params.json`.

## Install

### Claude Code

```
/plugin marketplace add nicholaslimck/freecad-3dprint
/plugin install freecad-3dprint@freecad-3dprint
```

### Other agents

Copy `skills/freecad-3dprint/` somewhere your agent can read it, then point the agent at `SKILL.md`, for example from your `AGENTS.md`. The skill refers to its own `kit/` and `references/` folders by relative path, so keep the folder intact.

## Quick start

Ask the agent for a part, for example "design a wall mount for a 60 mm round speaker, two M4 screws, PETG, no supports". On the first run it copies `kit/` into a project folder and checks your setup. You can run the same check yourself from the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step doctor
```

If FreeCAD isn't found, set `$env:FREECAD_CMD` to the full path of `FreeCADCmd.exe`.

The full pipeline is:

```powershell
powershell -ExecutionPolicy Bypass -File fcp\run.ps1          # build, check, render
powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Slice   # same, then slice
```

Without PowerShell, set `FCP_PROJECT` to the project folder and run the scripts in order:

```
FreeCADCmd.exe build.py
FreeCADCmd.exe fcp/check_print.py
FreeCADCmd.exe fcp/render_views.py
FreeCADCmd.exe fcp/slice.py
```

FreeCADCmd's exit code doesn't reliably reflect script errors, so each step writes its own status file to `out/`.

To slice with your printer's real settings, export a config from PrusaSlicer (File > Export > Export Config) and set `slicer.config` in `params.json`.

## Project layout

```
skills/freecad-3dprint/
  SKILL.md                  workflow the agent follows
  references/
    freecad-api.md          FreeCAD calls known to work, gotchas, common errors
    printability.md         wall, fit, fastener and overhang rules of thumb
  kit/                      copied into each new project
    build.py                parametric build script (example: a mounting plate)
    params.json             all dimensions and print settings
    spec.md                 requirements template
    fcp/
      cadlib.py             geometry helpers: holes, counterbores, teardrops, fillets, export
      check_print.py        printability checks -> out/report.json
      render_views.py       orthographic renders -> out/views/
      slice.py              slicer CLI wrapper -> out/slice_report.json
      doctor.py             environment check
      run.ps1               pipeline runner
```

## Limitations

The wall-thickness check samples points on each face and ray-marches inward, so it can miss very small features. The overhang check works from face angles and can't tell a short bridge from a long one. The renders exist to catch what these checks miss, so an agent that can't view images will ask you to look at them.

The printability numbers in `references/printability.md` are FDM starting points for a 0.4 mm nozzle. Printers differ, and the skill suggests printing a test coupon whenever a fit matters.

OrcaSlicer and Bambu Studio CLI flags change between versions. Check them against your slicer's `--help` before relying on the custom slicer template.

## Status

This is an early release (0.1.0). The pure-Python parts (overhang maths and slicer helpers) have tests in `tests/`; run them with `pip install numpy pytest && pytest`. Rendering is not tested yet. The FreeCAD-facing scripts have been checked for syntax but not yet run end to end against every FreeCAD release. Bug reports with the contents of `out/build_status.json` or `out/report.json` are welcome.

## License

MIT. See [LICENSE](LICENSE).
