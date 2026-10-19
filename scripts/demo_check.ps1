<#
.SYNOPSIS
    Sovereign Workbench Acceptance & Demo Verification Script (PowerShell wrapper).
.DESCRIPTION
    Runs the 5-step live verification against http://127.0.0.1:8000:
    1. /health endpoint (native host Ollama + models)
    2. Admin registration / authentication (password via env or secure prompt)
    3. Sample document upload & RAG ingestion
    4. Document question retrieval & citation check
    5. Calculator arithmetic tool invocation
.PARAMETER BaseUrl
    The base URL of the backend (default: http://127.0.0.1:8000)
.PARAMETER Username
    The admin username to register or log into (default: demo_admin)
.PARAMETER Password
    The admin password. If not provided, prompted securely or read from $env:ADMIN_PASSWORD
#>

param(
    [string]$BaseUrl = $env:BACKEND_URL,
    [string]$Username = $env:ADMIN_USERNAME,
    [string]$Password = $env:ADMIN_PASSWORD
)

if (-not $BaseUrl) { $BaseUrl = "http://127.0.0.1:8000" }
if (-not $Username) { $Username = "demo_admin" }

if (-not $Password) {
    $secPass = Read-Host -Prompt "Enter admin password for user '$Username'" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPass)
    $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
}

$env:ADMIN_PASSWORD = $Password
$env:ADMIN_USERNAME = $Username
$env:BACKEND_URL = $BaseUrl

$pythonExe = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

$scriptPath = Join-Path $PSScriptRoot "demo_check.py"
& $pythonExe $scriptPath --base-url $BaseUrl --username $Username --password $Password
exit $LASTEXITCODE
