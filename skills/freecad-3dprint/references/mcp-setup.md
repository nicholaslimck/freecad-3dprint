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

**Upstream:** this is [neka-nat/freecad-mcp#115](https://github.com/neka-nat/freecad-mcp/issues/115),
open and unfixed. The reporter's trigger is a broken FeaturePython object; the
repro above needs no such object. The hard crash has no matching issue.

**What to do:**

- Do not use `execute_code_async` to build geometry. Use
  `execute_code_headless`, which runs in a separate `freecadcmd` process and
  cannot take the GUI down.
- Treat the live path as best-effort for `get_view` only, and expect to restart
  FreeCAD afterwards.
- If the probe says `timed out`, tell the user to restart FreeCAD rather than
  guessing at firewalls.
