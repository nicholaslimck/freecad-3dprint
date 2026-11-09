# Optional: live FreeCAD over MCP

This is an **accelerator, never a requirement**. Everything in this skill works
with a plain `FreeCADCmd` install and no MCP server at all. The gate, the checks
and the slicer step never touch MCP.

With the server running you get a live FreeCAD GUI you can build in, move the
camera, and screenshot — useful when the user says *"show me what that would
look like"*. Without it, you render candidates with `render_views.py` as usual.

## What it gives you

- A real GUI session you can add shapes to, and `get_view` screenshots from.
- A managed headless runner with a real exit code.
- Nothing that can write `print_gate.json` or `slice_report.json`. Those stay
  headless and file-driven, so a GUI can never certify a part printable.

## 1. Install the addon

The addon lives in the **versioned** FreeCAD user directory:

```
%APPDATA%\FreeCAD\v<major>-<minor>\Mod\FreeCADMCP\
```

On the machine this was written on that is
`%APPDATA%\FreeCAD\v1-1\Mod\FreeCADMCP`, and it is already present:
addon **0.1.30**, protocol **1**. If `Mod\FreeCADMCP` is missing, copy it from
the addon's release archive into that path. The version segment matters: a
`Mod` folder under an unversioned `FreeCAD\` path is not loaded by 1.x.

## 2. Enable auto-start

Settings file: `%APPDATA%\FreeCAD\v1-1\freecad_mcp_settings.json`

```json
{
  "remote_enabled": false,
  "allowed_ips": "127.0.0.1",
  "auto_start_rpc": true,
  "auth_token": ""
}
```

Set `auto_start_rpc` to `true` so the RPC server starts with FreeCAD. The
addon's own menu has the same toggle if you prefer the GUI.

## 2a. Windows: `freecadcmd` must be on PATH

`execute_code_headless` shells out to `freecadcmd`, and the server finds it with
`detect_freecadcmd()`, which searches **PATH, then Flatpak** — it does not look in
`C:\Program Files\FreeCAD*\bin\`. On a default Windows install `freecadcmd.exe`
is not on PATH, so the tool fails with:

```
Headless FreeCAD script FAILED: freecadcmd not found: install FreeCAD, or pass --freecadcmd to freecad-mcp
```

Add FreeCAD's `bin` to the user PATH once:

```powershell
$bin = "C:\Program Files\FreeCAD 1.1\bin"
$old = [Environment]::GetEnvironmentVariable("Path", "User")
if ($old -notmatch [regex]::Escape($bin)) {
    [Environment]::SetEnvironmentVariable("Path", ($old.TrimEnd(';') + ";" + $bin), "User")
}
```

Then **restart the process that launched the MCP server**, not just the server.
Child processes inherit the environment from their parent, so if your editor or
agent host was already running when you changed PATH, every MCP process it
spawns keeps the old one. Verify with a fresh shell:

```powershell
python -c "import shutil; print(shutil.which('freecadcmd'))"
```

Passing `--freecadcmd` is the alternative, but on Windows the flag currently
mangles backslash paths ([#178](https://github.com/neka-nat/freecad-mcp/issues/178)
item 7). Use forward slashes and embedded quotes:
`--freecadcmd "\"C:/Program Files/FreeCAD 1.1/bin/freecadcmd.exe\""`.

## 3. Start FreeCAD and verify

With FreeCAD open and the server started:

```powershell
python skills/freecad-3dprint/kit/fcp/mcp_probe.py
```

```json
{
  "available": true,
  "endpoint": "127.0.0.1:9875",
  "protocol_version": 1,
  "addon_version": "0.1.30",
  "reason": "ok"
}
```

The probe is stdlib only: it needs no FreeCAD and no numpy, so it is safe to run
from any Python. Inside FreeCAD you can also start the server by hand:

```python
import rpc_server
rpc_server.start_rpc_server()
```

## 4. Tell your harness about it

Any MCP client that can launch the addon's server works; this skill detects the
server by its **RPC port**, not by how your harness happens to be configured. So
the setup steps are the same for OpenCode, Claude Code, Codex, or anything else.

## Security

- The server binds `127.0.0.1:9875` and checks the `Host` header against
  localhost, so a web page in a browser cannot reach it.
- `remote_enabled: true` exposes `0.0.0.0`. Only do that with a non-empty
  `auth_token`, and understand that anyone who can reach the port can run code.
- `execute_code` runs arbitrary Python inside FreeCAD. That is the same trust
  level as running the build script yourself, and no higher.

## Troubleshooting

| `reason` | Meaning | Fix |
|---|---|---|
| `connection refused` | nothing is listening on the port | FreeCAD is closed or the RPC server never started |
| `timed out` | something holds the port but does not answer | **FreeCAD's GUI thread is wedged** - see "Known crash" below. Restart FreeCAD; a firewall is the other possibility |
| `not an XML-RPC server: ...` | something else answered on 9875 | stop that service, or accept that MCP is unavailable |
| `wrong protocol version: server N, probe 1` | addon and probe disagree | update the addon so its `PROTOCOL_VERSION` matches the probe's |

`available: false` is never a problem for the design work. Say so once, offer
this file, and carry on headless.

`timed out` and `connection refused` mean different things and the probe keeps
them apart on purpose: **refused** is a clean "no server", **timed out** is a
server that accepted the connection and then stopped responding, which is the
wedged-GUI failure below, not a missing install.

## Known crash: `execute_code_async` wedges or kills FreeCAD

Observed on Windows, FreeCAD 1.1.4, addon 0.1.30. Both repros are minimal and
need no workbench:

```python
# 1. wedges the GUI thread: server stays listening, never answers
import FreeCAD
doc = FreeCAD.newDocument("scratch_probe")     # enough on its own

# 2. second attempt killed the process outright
```

Symptoms, in order:

- `execute_code_async` returns a job id, then `get_async_status` times out.
- `FreeCAD.exe` shows `Responding: False` with a flat CPU count - blocked, not
  spinning. `mcp_probe` flips to `timed out`.
- After a restart the same call crashed the process: Windows Application log
  shows `BEX64` / `c0000409` (fail-fast) in `ucrtbase.dll`. `freecadcmd.exe`
  hosting the addon crashes separately in `Qt6Core.dll`.

Confirmed twice on this machine: the crash comes from the **call itself**, not
from what the code does. A one-line `FreeCAD.newDocument(...)`, and separately a
`FreeCAD.openDocument(...)`, both killed FreeCAD outright.

**Upstream:** the hang is [neka-nat/freecad-mcp#115](https://github.com/neka-nat/freecad-mcp/issues/115),
open and unfixed. The reporter's trigger is a broken FeaturePython object; the
repros above need no such object. The hard crash has no matching issue.

## If `execute_code_async` kills FreeCAD

Treat it as a normal outcome, not an emergency:

1. **Say so once** and name the cause (it is an addon crash, not the user's
   geometry, and not something the design did). Do not retry it - the retry
   crashes it again.
2. **Restart FreeCAD**, and reopen whatever document the user had.
3. **Carry on with the alternatives.** In order of preference:

   | Instead of async | Use |
   |---|---|
   | building or modifying geometry | `execute_code_headless` |
   | running the real pipeline | `fcp/run.ps1`, or `FreeCADCmd.exe build.py` etc. |
   | showing the user the result | `.out/views/<stem>_sheet.png` from the render step |

   All three are separate processes and cannot take the GUI down.
4. **Do not depend on `get_view`.** If FreeCAD died, there is no GUI to
   screenshot, and the only way to load a document into it is `execute_code_async`
   - the call that just crashed it. The contact sheet is the deliverable.

Nothing in the design, check, slice or gate path needs MCP; losing it costs a
convenience, never a result. This is exactly why the skill treats MCP as an
accelerator.

### What has actually been proven to work

Verified on Windows, FreeCAD 1.1.4, addon 0.1.30:

| Call | Result |
|---|---|
| `mcp_probe` against a live server | works - `available: true`, protocol 1 |
| `get_rpc_status` | works - reports GUI dispatch health |
| `execute_code_headless` building geometry, saving a `.FCStd`, returning output | works |
| `execute_code_async` | **crashes FreeCAD** |
| `get_view` on an open document | runs and returns a PNG, but the capture was blank - see below |

### A headless-built document opens with everything hidden

`execute_code_headless` has no GUI, so every object it creates has
`ViewObject: None` - there is no view provider to attach a view to. When the GUI
later opens that `.FCStd`, the objects are present but **hidden**, and
`get_view` returns a blank image with no error. Setting `Visibility = True`
before `saveAs` does not survive: the file was reopened and the parts were still
hidden.

So the round trip "build headlessly, save, open in the GUI, screenshot it" does
not work. The practical consequence:

- **Do not build review candidates in headless FreeCAD and hand the user a
  `.FCStd` expecting them to see the shapes.** They will open an empty view.
- **Use the contact sheet** (`render_lines.contact_sheet` / `fcp/run.ps1`). It is
  a real image, needs no GUI, and is what the skill delivers anyway.
- Building candidates *inside* the running GUI needs `execute_code_async`, which
  crashes FreeCAD here. There is currently no working path to a live 3D view.

None of this blocks the design loop. It only removes the "show me live" nicety
the skill offered.

