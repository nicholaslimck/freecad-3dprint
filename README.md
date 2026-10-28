# freecad-3dprint

An agent skill for designing 3D-printable parts in FreeCAD on Windows. The agent writes a parametric Python script, FreeCAD runs it headless, and a set of checks reports whether the part will print. The agent never touches the FreeCAD GUI. It reads a JSON report, looks at rendered views of the part, and can slice the part with your own printer profile before it calls the job done.

It works with Claude Code as a plugin, and with any other agent that can read a markdown file and run commands on a Windows machine.

## How it works

The agent follows six steps, which are written out in [`SKILL.md`](skills/freecad-3dprint/SKILL.md).

1. It agrees a spec with you first: measured dimensions of everything the part mates with, fits, material, print orientation, whether supports are acceptable, how a latch will retain, and what a coupon will test. It won't start modelling until you confirm.
2. It puts every dimension in `params.json` and writes one Python function per feature in `build.py`, with a single `build(params)` that coupons reuse.
3. It runs the pipeline, reads `.out/report.json`, looks at the rendered views, and fixes what's wrong. A flat downward face is classified as a bridge, cantilever or unsupported shelf from where the geometry is anchored. It may not loosen a check to make it pass without your agreement, and it stops to ask after three failed attempts at the same error.
4. If you have PrusaSlicer (or another slicer with a CLI), it slices the part with supports off and reads back print time, filament and warnings. Without a slicer, you look at the preview and record the check in `params.json`.
5. A print gate decides whether the part is printable. It refuses while a warning is untriaged, an output is stale, or no slice/manual preview exists.
6. It hands over the exact file to print from `.out/manifest.json`, the FreeCAD file and a STEP, along with a summary and what to test-print first.

The checks in `report.json` cover:

- shape validity, solid count and per-component volume/bbox (a floating feature is an error)
- declared points that must be inside the part (latch and hinge roots)
- the expected bounding box, which catches scale and axis mistakes
- whether the mesh is watertight and manifold
- walls thinner than `print.min_wall`
- overhangs steeper than `print.max_overhang_deg`
- flat downward faces, classified as `bridge`, `cantilever`, `unsupported` or `supported` with area, span, center and anchors
- bed contact area and tall, thin parts
- whether the part fits the build volume
- horizontal holes that would print better as teardrops
- declared clearance/interference between named parts (`distToShape` and intersection volume)
- coupons that are not cut from the real part

Every finding has a stable `code`, so a warning can be accepted in
`params.checks.accept` with a reason and evidence. A face declared as a bridge
that the geometry shows as a cantilever is an error, not a warning.

The renders are a six-view contact sheet in print orientation: red is a steep
overhang, amber is a flat down face that is a cantilever or unsupported shelf.
`render.features` adds a close-up and section per feature (a latch, a bead, a
hinge) so a small undercut is visible without opening FreeCAD.

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

### OpenCode, Codex, Gemini CLI

These all load skills from `~/.agents/skills/<name>/SKILL.md`, so one copy covers all three. In PowerShell:

```powershell
git clone https://github.com/nicholaslimck/freecad-3dprint "$HOME\src\freecad-3dprint"
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -Recurse "$HOME\src\freecad-3dprint\skills\freecad-3dprint" "$HOME\.agents\skills\"
```

To update, `git pull` in the clone, delete `$HOME\.agents\skills\freecad-3dprint`, and copy it again. For a single project instead of every project, copy the folder into `<project>\.agents\skills\` instead.

Each tool also has its own location if you prefer:

| Agent | User-wide | Per project |
|---|---|---|
| OpenCode | `~/.config/opencode/skills/` (also reads `~/.claude/skills/`) | `.opencode/skills/` |
| Gemini CLI | `~/.gemini/skills/`, or `gemini skills install https://github.com/nicholaslimck/freecad-3dprint.git --path skills/freecad-3dprint` | `.gemini/skills/` |
| Claude Code (without the plugin) | `~/.claude/skills/` | `.claude/skills/` |

### Any other agent

Copy `skills/freecad-3dprint/` somewhere your agent can read it, then point the agent at `SKILL.md`, for example from your `AGENTS.md`.

Whichever way you install, keep the folder intact and named `freecad-3dprint`. The skill refers to its own `kit/` and `references/` folders by relative path, and skill loaders expect the folder name to match the `name` in `SKILL.md`.

## Quick start

Ask the agent for a part, for example "design a wall mount for a 60 mm round speaker, two M4 screws, PETG, no supports". On the first run it creates `<project>\.freecad-3dprint\`, copies `kit/` there, and checks your setup. All work happens inside that hidden workspace, so your project folder keeps its normal files. Run the same check yourself from inside it:

```powershell
cd .freecad-3dprint
powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step doctor
```

If FreeCAD isn't found, set `$env:FREECAD_CMD` to the full path of `FreeCADCmd.exe`.

The full pipeline, run from inside the workspace:

```powershell
powershell -ExecutionPolicy Bypass -File fcp\run.ps1           # build, check, render, gate
powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Slice    # same, then slice
powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step release   # verified files -> print/<stem>/
powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step status    # current version, gate, file to print
```

`run.ps1` exits 0 only when the print gate says the part is printable. Until a
slice (supports off) or a recorded manual preview exists, it exits 1 and names
what is missing. Once it passes, `-Step release` copies the verified STL/3MF,
STEP, FCStd, report and gate into `<project>/print/<stem>/` with a README and
hashes. That folder is the deliverable and is safe to commit; `.out/` is
regenerable and ignored by the workspace `.gitignore`.

Without PowerShell, set `FCP_PROJECT` to the workspace (`.freecad-3dprint`) and run the scripts in order from inside it:

```
FreeCADCmd.exe build.py
FreeCADCmd.exe fcp/check_print.py
FreeCADCmd.exe fcp/render_views.py
FreeCADCmd.exe fcp/slice.py
FreeCADCmd.exe fcp/gate.py
```

FreeCADCmd's exit code doesn't reliably reflect script errors (and it does not set
`__name__ == "__main__"`), so each step writes its own status file to `.out/`.

To slice with your printer's real settings, export a config from PrusaSlicer (File > Export > Export Config) and set `slicer.config` in `params.json`.

## Repo layout

```
skills/freecad-3dprint/
  SKILL.md                  workflow the agent follows
  references/
    freecad-api.md          FreeCAD calls known to work, gotchas, common errors
    printability.md         wall, fit, fastener and overhang rules of thumb
    latches-and-snaps.md    latch/snap design, orientation flips, decision table
  kit/                      copied into each new project
    build.py                parametric build script (example: a mounting plate)
    params.json             all dimensions, check expectations, coupon and print settings
    spec.md                 requirements template
    fcp/
      cadlib.py             geometry helpers: holes, counterbores, teardrops, fillets,
                            section/coupon, export + manifest, no-BOM writes
      analysis.py           pure-numpy flat-face regions and bridge/cantilever classification
      check_print.py        printability checks -> .out/report.json
      render_views.py       orthographic, detail and section renders -> .out/views/
      slice.py              slicer CLI wrapper -> .out/slice_report.json
      gate.py               print gate -> .out/print_gate.json
      release.py            verified files -> <project>/print/<stem>/
      status.py             current version, gate state, exact file -> .out/status.json
      doctor.py             environment, BOM and params check
      run.ps1               pipeline runner
  tests/ (repo root)        pure-python tests and FreeCAD end-to-end cases
```

## Project layout

```
<project>/
  .freecad-3dprint/   created by the skill; the working directory for every step
    .gitignore                 ignores .out/ (sources are committed)
    build.py                   features and build(params)
    params.json                dimensions, checks, coupon, print settings
    spec.md                    requirements and triage
    fcp/                       checks, renders, slicer, gate, release, runner
    .out/                      generated: reports, renders, STL/3MF, manifest, gate
  print/
    <name>_v3/                 released after the gate passes; safe to commit
      <name>_v3_print.3mf
      <name>_v3.step
      <name>_v3.FCStd
      report.json, print_gate.json, release.json, README.md
```

The project folder itself keeps whatever else belongs to the part: datasheets,
photos, the user's own notes. `run.ps1 -Step release` refuses unless the print
gate says the current design is printable.

## Limitations

The wall-thickness check samples points on each face and ray-marches inward, so it
can miss very small features. The support classification is geometric and
heuristic: it groups horizontal down faces, probes just outside their boundary for
material, and calls a face a bridge when anchors enclose its centroid. A curved,
diagonal or very small shelf can be misclassified, so the result is reported with
its anchors and support fraction and is always backed by the slicer/preview gate.
It is not a substitute for looking at the layers.

The renders exist to catch what these checks miss, so an agent that can't view
images will ask you to look at them.

The printability numbers in `references/printability.md` are FDM starting points for a 0.4 mm nozzle. Printers differ, and the skill suggests printing a test coupon whenever a fit matters. Coupons are sections of the real part, not standalone blocks.

OrcaSlicer and Bambu Studio CLI flags change between versions. Check them against your slicer's `--help` before relying on the custom slicer template.

## Status

This is an early release (0.4.0). The pure-Python parts (overhang maths, support
classification, slicer and gate helpers) have tests in `tests/`; run them with
`pip install numpy pytest && pytest`. `tests/e2e_cases.py` builds the failure
cases from the improvement handoff as throwaway projects through FreeCADCmd
(cantilever shelf, two-tower bridge, disconnected hook, BOM, coupon section) and
needs FreeCAD installed. Rendering is not pixel-tested. Bug reports with the
contents of `.out/build_status.json` or `.out/report.json` are welcome.

## License

MIT. See [LICENSE](LICENSE).
