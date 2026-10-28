<#
.SYNOPSIS
  Build -> check -> render (-> slice) -> gate pipeline for a FreeCAD 3D-print project.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File fcp\run.ps1             # build, check, render, gate
  powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Slice      # ...and slice
  powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step gate
  powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step doctor
  powershell -ExecutionPolicy Bypass -File fcp\run.ps1 -Step clean
.NOTES
  FreeCADCmd is found via $env:FREECAD_CMD, then Program Files / LocalAppData, then PATH.
  Exit code: 0 = all requested steps passed AND the print gate says printable.
  1 = something failed (details in .out\*.json). A part without a clean slice or a
  recorded manual supports-off preview is NOT printable, so the run fails at the gate.
#>
param(
  [ValidateSet("all", "build", "check", "render", "slice", "gate", "doctor", "clean")]
  [string]$Step = "all",
  [switch]$Slice
)
$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent $PSScriptRoot
$env:FCP_PROJECT = $Project
$Out = Join-Path $Project ".out"

function Find-FreeCADCmd {
  if ($env:FREECAD_CMD -and (Test-Path $env:FREECAD_CMD)) { return $env:FREECAD_CMD }
  $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA "Programs")) | Where-Object { $_ }
  foreach ($r in $roots) {
    $hit = Get-ChildItem -Path (Join-Path $r "FreeCAD*\bin\FreeCADCmd.exe") -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending | Select-Object -First 1
    if ($hit) { return $hit.FullName }
  }
  $cmd = Get-Command FreeCADCmd.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  throw "FreeCADCmd.exe not found. Set `$env:FREECAD_CMD to its full path."
}

function Invoke-FC([string]$script) {
  # PS 5.1 turns redirected stderr lines into errors; "Stop" would abort on any warning.
  $ErrorActionPreference = "Continue"
  Push-Location $Project
  try { & $script:FC $script 2>&1 | ForEach-Object { "$_" } } finally { Pop-Location }
}

function Read-Status([string]$name) {
  $p = Join-Path $Out $name
  if (-not (Test-Path $p)) { return $null }
  return Get-Content $p -Raw | ConvertFrom-Json
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null

if ($Step -eq "clean") {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $dest = Join-Path $Out "archive\$stamp"
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  Get-ChildItem $Out -Force | Where-Object { $_.Name -ne "archive" } |
    Move-Item -Destination $dest -Force
  Write-Host "archived .out\ -> $dest"
  exit 0
}

$script:FC = Find-FreeCADCmd
Write-Host "FreeCADCmd: $script:FC"
$failed = $false

if ($Step -eq "doctor") {
  Remove-Item (Join-Path $Out "doctor.json") -ErrorAction SilentlyContinue
  Invoke-FC (Join-Path $PSScriptRoot "doctor.py")
  $d = Read-Status "doctor.json"
  if (-not $d -or -not $d.ok) { Write-Host "DOCTOR FAILED - see .out\doctor.json"; exit 1 }
  exit 0
}

if ($Step -in @("all", "build")) {
  Remove-Item (Join-Path $Out "build_status.json") -ErrorAction SilentlyContinue
  Remove-Item (Join-Path $Out "slice_report.json") -ErrorAction SilentlyContinue  # new export invalidates the slice
  Invoke-FC (Join-Path $Project "build.py")
  $s = Read-Status "build_status.json"
  if (-not $s -or -not $s.ok) { Write-Host "BUILD FAILED - see .out\build_status.json"; exit 1 }
}
if ($Step -in @("all", "check")) {
  Remove-Item (Join-Path $Out "report.json") -ErrorAction SilentlyContinue
  Invoke-FC (Join-Path $PSScriptRoot "check_print.py")
  $r = Read-Status "report.json"
  if (-not $r -or -not $r.pass) { $failed = $true }
}
if ($Step -in @("all", "render")) {
  Remove-Item (Join-Path $Out "render_status.json") -ErrorAction SilentlyContinue
  Invoke-FC (Join-Path $PSScriptRoot "render_views.py")
  $v = Read-Status "render_status.json"
  if (-not $v -or -not $v.ok) { $failed = $true }
}
if ($Slice -or $Step -eq "slice") {
  Remove-Item (Join-Path $Out "slice_report.json") -ErrorAction SilentlyContinue
  Invoke-FC (Join-Path $PSScriptRoot "slice.py")
  $sl = Read-Status "slice_report.json"
  if (-not $sl -or -not $sl.ok) { $failed = $true }
}
if ($Step -in @("all", "gate")) {
  Remove-Item (Join-Path $Out "print_gate.json") -ErrorAction SilentlyContinue
  Invoke-FC (Join-Path $PSScriptRoot "gate.py")
  $g = Read-Status "print_gate.json"
  if (-not $g -or -not $g.printable) {
    Write-Host "PRINT GATE: not printable - see .out\print_gate.json"
    $failed = $true
  } else {
    Write-Host "PRINT GATE: printable"
  }
}
if ($failed) { exit 1 } else { exit 0 }

