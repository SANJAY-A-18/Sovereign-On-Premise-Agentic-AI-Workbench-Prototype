# PowerShell wrapper for scripts/reset_dev_state.py
param(
    [switch]$Force,
    [switch]$Yes,
    [switch]$NoBackup
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

$ArgsList = @("$ScriptDir\reset_dev_state.py")
if ($Force) { $ArgsList += "--force" }
if ($Yes) { $ArgsList += "--yes" }
if ($NoBackup) { $ArgsList += "--no-backup" }

& $PythonExe @ArgsList
exit $LASTEXITCODE
