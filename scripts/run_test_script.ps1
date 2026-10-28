<#
.SYNOPSIS
    PowerShell wrapper for running the Sovereign AI Workbench automated test runner.

.DESCRIPTION
    Executes scripts/run_test_script.py using the project's local virtual environment (.venv).
    Guarantees strict isolation against a temporary data directory (never touches real data/).

.PARAMETER Live
    Runs live Ollama model tests (qwen2.5:3b and nomic-embed-text) if host Ollama is reachable.

.PARAMETER Report
    Generates a timestamped markdown report in docs/TEST_RESULTS_<date>.md.

.PARAMETER Verbose
    Prints detailed step diagnostic output.

.EXAMPLE
    .\scripts\run_test_script.ps1
    .\scripts\run_test_script.ps1 -Report
    .\scripts\run_test_script.ps1 -Live -Report
#>

[CmdletBinding()]
param(
    [switch]$Live,
    [switch]$Report,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Virtual environment Python executable not found at: $PythonExe"
    exit 1
}

$TestScript = Join-Path $ProjectRoot "scripts\run_test_script.py"

$ArgsList = @()
if ($Live) { $ArgsList += "--live" }
if ($Report) { $ArgsList += "--report" }
if ($Verbose) { $ArgsList += "--verbose" }

& $PythonExe $TestScript @ArgsList
exit $LASTEXITCODE
