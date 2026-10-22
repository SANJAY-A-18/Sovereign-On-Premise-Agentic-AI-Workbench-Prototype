<#
.SYNOPSIS
    Sovereign On-Premise Agentic AI Workbench - Primary Native Demo Launcher.
.DESCRIPTION
    Launches the full Sovereign Workbench stack natively from the local Python virtual environment:
    1. Validates .venv and required dependencies
    2. Checks native host Ollama runtime & models (qwen2.5:3b, nomic-embed-text)
    3. Ensures valid JWT secret exists in .env (generates one if needed)
    4. Starts the FastAPI backend on http://127.0.0.1:8000
    5. Waits for backend /live readiness
    6. Starts the Streamlit Web UI on http://127.0.0.1:8501
    7. Prints active service URLs and manages process lifecycles
#>

[CmdletBinding()]
param(
    [string]$HostAddress = "127.0.0.1",
    [int]$BackendPort = 8000,
    [int]$UiPort = 8501
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   SOVEREIGN ON-PREMISE AGENTIC AI WORKBENCH - NATIVE LAUNCHER        " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python Virtual Environment
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Virtual environment not found at .venv" -ForegroundColor Red
    Write-Host "Please create the virtual environment first:" -ForegroundColor Yellow
    Write-Host "    python -m venv .venv" -ForegroundColor Yellow
    Write-Host "    .\.venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Using Python virtual environment: $PythonExe" -ForegroundColor Green

# 2. Check Native Host Ollama Status
Write-Host "[INIT] Checking native host Ollama (http://localhost:11434)..." -ForegroundColor Yellow
$OllamaHealthy = $false
try {
    $OllamaResponse = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -TimeoutSec 3 -ErrorAction Stop
    $ModelNames = $OllamaResponse.models | ForEach-Object { $_.name }
    Write-Host "[OK] Host Ollama is active. Installed models: $($ModelNames -join ', ')" -ForegroundColor Green
    $OllamaHealthy = $true
} catch {
    Write-Host "[WARN] Ollama is not responding at http://localhost:11434." -ForegroundColor Yellow
    Write-Host "       The workbench will launch in degraded mode (readiness /health degraded)." -ForegroundColor Yellow
    Write-Host "       To enable full LLM generation and RAG embeddings, start Ollama in another terminal:" -ForegroundColor Yellow
    Write-Host "           ollama serve" -ForegroundColor Yellow
    Write-Host "           ollama pull qwen2.5:3b" -ForegroundColor Yellow
    Write-Host "           ollama pull nomic-embed-text" -ForegroundColor Yellow
    Write-Host ""
}

# 3. Ensure Valid JWT Secret in .env
$EnvFile = Join-Path $ProjectRoot ".env"
$GenSecretScript = Join-Path $ProjectRoot "scripts\gen_secret.py"
$SecretValid = $false
if (Test-Path $EnvFile) {
    & $PythonExe $GenSecretScript --check | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $SecretValid = $true
    }
}
if (-not $SecretValid) {
    Write-Host "[INIT] Generating cryptographically secure JWT_SECRET_KEY into .env..." -ForegroundColor Yellow
    & $PythonExe $GenSecretScript --write
}
Write-Host "[OK] JWT Authentication secret verified in .env" -ForegroundColor Green

# 4. Start FastAPI Backend Process
Write-Host "[INIT] Starting FastAPI Backend on http://${HostAddress}:${BackendPort}..." -ForegroundColor Yellow
$BackendCmd = "$PythonExe -m uvicorn backend.main:app --host $HostAddress --port $BackendPort"
$BackendProcess = Start-Process -FilePath $PythonExe `
    -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", $HostAddress, "--port", $BackendPort `
    -WorkingDirectory $ProjectRoot `
    -PassThru

# 5. Wait for Backend Liveness
$BackendLive = $false
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $liveRes = Invoke-RestMethod -Uri "http://${HostAddress}:${BackendPort}/live" -Method Get -TimeoutSec 1 -ErrorAction Stop
        if ($liveRes.status -eq "alive") {
            $BackendLive = $true
            break
        }
    } catch {
        # Keep waiting
    }
}

if (-not $BackendLive) {
    Write-Host "[ERROR] Backend process failed to respond on /live within 15 seconds." -ForegroundColor Red
    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        Stop-Process -Id $BackendProcess.Id -Force
    }
    exit 1
}
Write-Host "[OK] Backend process is healthy and listening (PID: $($BackendProcess.Id))" -ForegroundColor Green

# 6. Start Streamlit Web UI Process
Write-Host "[INIT] Starting Streamlit Web UI on http://${HostAddress}:${UiPort}..." -ForegroundColor Yellow
$UiProcess = Start-Process -FilePath $PythonExe `
    -ArgumentList "-m", "streamlit", "run", "ui/app.py", "--server.port", $UiPort, "--server.address", $HostAddress `
    -WorkingDirectory $ProjectRoot `
    -PassThru

# Wait briefly for Streamlit
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "             SOVEREIGN WORKBENCH IS NOW RUNNING NATIVELY              " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "  Streamlit Web UI:        http://${HostAddress}:${UiPort}" -ForegroundColor Cyan
Write-Host "  FastAPI REST API Docs:   http://${HostAddress}:${BackendPort}/docs" -ForegroundColor Cyan
Write-Host "  System Health Check:     http://${HostAddress}:${BackendPort}/health" -ForegroundColor Cyan
Write-Host "  System Liveness Check:   http://${HostAddress}:${BackendPort}/live" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "Press Ctrl+C to terminate both servers..." -ForegroundColor Yellow
Write-Host ""

try {
    while ($true) {
        if ($BackendProcess.HasExited) {
            Write-Host "[WARN] Backend process terminated unexpectedly." -ForegroundColor Red
            break
        }
        if ($UiProcess.HasExited) {
            Write-Host "[WARN] Streamlit UI process terminated." -ForegroundColor Yellow
            break
        }
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host "`n[SHUTDOWN] Stopping background services..." -ForegroundColor Yellow
    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        Stop-Process -Id $BackendProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Backend process stopped." -ForegroundColor Green
    }
    if ($UiProcess -and -not $UiProcess.HasExited) {
        Stop-Process -Id $UiProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Streamlit UI stopped." -ForegroundColor Green
    }
    Write-Host "[SHUTDOWN] All services terminated cleanly." -ForegroundColor Green
}
