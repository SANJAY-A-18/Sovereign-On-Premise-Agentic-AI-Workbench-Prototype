# Sovereign On-Premise Agentic AI Workbench: Deployment Guide

This document describes the Docker Hub one-command deployment workflow, native quickstart, air-gapped offline transfer procedure, memory resource benchmarks, and 8 GB RAM optimization guidelines for the **Sovereign On-Premise Agentic AI Workbench**.

---

## 1. Architectural Model & Deployment Strategy

```
Host Windows Machine (8 GB RAM Budget, No GPU)
┌────────────────────────────────────────────────────────────────────────┐
│ Native Windows Host:                                                   │
│   • Ollama Engine (http://localhost:11434)                             │
│     - Model: qwen2.5:3b (quantized Q4_K_M)                             │
│     - Embeddings: nomic-embed-text                                     │
│     - Context: num_ctx <= 4096                                         │
│                                                                        │
│ Docker Isolated Network Bridge (Internal Container Communication):    │
│   ┌──────────────────────────────┐     ┌─────────────────────────────┐ │
│   │ sovereign-ui                 │────►│ sovereign-backend           │ │
│   │ Port 8501 (127.0.0.1 only)   │     │ Port 8000 (127.0.0.1 only)  │ │
│   │ Non-root user (appuser)      │     │ Non-root user (appuser)     │ │
│   └──────────────────────────────┘     └──────────────┬──────────────┘ │
│                                                       │                │
│                                  Resolves host Ollama │                │
│                         via host.docker.internal:11434│                │
│                                                       ▼                │
│                                        ┌─────────────────────────────┐ │
│                                        │ Named Volume: sovereign_data│ │
│                                        │ Mount: /app/data            │ │
│                                        │ • sovereign.db (SQLite WAL) │ │
│                                        │ • demo.db (Read-only SQL)   │ │
│                                        │ • chroma/ (Local Vectors)   │ │
│                                        │ • uploads/ (Raw Files)      │ │
│                                        └─────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

### Core Architecture Principles
1. **Ollama Runs Natively on Host**: Ollama is **never** containerized. Placing 3B model weights inside a virtualized container on an 8 GB host creates unnecessary virtualization memory overhead.
2. **Localhost-Only Ingress**: Ports `8000` (FastAPI) and `8501` (Streamlit) bind strictly to `127.0.0.1`. Containers are unreachable from the LAN.
3. **Internal Container Networking**: The UI reaches the backend via Docker DNS `http://backend:8000`. The backend resolves host Ollama via `host.docker.internal:11434` (with `host-gateway` mapping for Linux).
4. **Persistent Named Volume**: `sovereign_data` mounts into `/app/data` to persist SQLite databases, audit trails, and ChromaDB vector indices across container restarts.

---

## 2. Quickstart & Execution Paths

### Primary Demo Path: Native Virtual Environment Launcher
For evaluation, demonstration, and daily development on Windows laptops with 8 GB RAM, running natively from the Python `.venv` is the **recommended primary path**:

```powershell
# One-command native launch (starts backend + Streamlit UI + Ollama check)
.\scripts\run_native.ps1
```
This launcher:
1. Validates the `.venv` Python runtime.
2. Checks that native host Ollama (`http://localhost:11434`) is running with required models (`qwen2.5:3b`, `nomic-embed-text`).
3. Automatically generates a secure 256-bit JWT secret in `.env` if missing.
4. Starts FastAPI on `http://127.0.0.1:8000` and verifies `/live` responsiveness.
5. Starts Streamlit on `http://127.0.0.1:8501`.
6. Prints all service endpoints and handles clean shutdown on `Ctrl+C`.

---

### Secondary Deployment Path: Docker Compose Containers

#### Prerequisites
- Native **Ollama** installed on the host and running (`ollama serve`).
- **Docker** and **Docker Compose v2** installed with WSL2 on Windows.

> [!NOTE]
> **Environment & Verification Transparency:**
> Docker Desktop and WSL2 were **not run locally on the development laptop** because WSL2 is not installed on this machine (`wsl -l -v` returned `The Windows Subsystem for Linux is not installed`).
> All container packaging, Dockerfiles, and compose configurations are automated and verified via GitHub Actions CI ([.github/workflows/docker-ci.yml](file:///c:/Users/SanjayAnandhakumar/Desktop/FYP/.github/workflows/docker-ci.yml)).

#### 3-Command Launch
```powershell
# 1. Generate a cryptographically secure 256-bit JWT secret in .env
python scripts/gen_secret.py --write

# 2. Build the production runtime containers (pinned requirements.txt only)
docker compose build

# 3. Launch the full sovereign workbench stack in the background
docker compose up -d
```

### Accessing the Workbench
- **Streamlit Web UI**: [http://127.0.0.1:8501](http://127.0.0.1:8501)
- **FastAPI Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **System Health Status (Readiness)**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- **System Liveness Status**: [http://127.0.0.1:8000/live](http://127.0.0.1:8000/live)

### Running Acceptance & Demo Verification
Verify all 5 end-to-end workflows (Ollama health, admin authentication, document upload, RAG retrieval question with citations, and arithmetic calculation with run trace assertion):
```powershell
python scripts/demo_check.py --password "YourAdminPassword123!"
```
Or via PowerShell wrapper:
```powershell
.\scripts\demo_check.ps1 -Password "YourAdminPassword123!"
```
*(When no backend is active, `scripts/demo_check.py` automatically spawns an ephemeral backend using a temporary `SOVEREIGN_DATA_DIR` to guarantee the real `data/` directory is never modified).*

---

## 3. Run from Docker Hub on another laptop

This deployment path enables running the Sovereign Workbench on another laptop (Windows, macOS, or Linux) with Docker Desktop installed—without needing to install Python, clone the full git repository, or manually install and manage Ollama on the host machine.

### Prerequisites
- **Docker Desktop** (with WSL2 backend on Windows, or Docker Engine on Linux/macOS) installed and running.
- **Docker Desktop memory allocation**: Configure Docker Desktop memory to **at least 4 GB** (**6 GB or more** on 16 GB laptops), because the containerized Ollama engine requires about 2.3 GB during active model inference.
- **About 6 GB free disk space**:
  - Container images (`sovereign-backend`, `sovereign-ui`, and `ollama/ollama`): ~1.8 GB combined.
  - Model weights: `qwen2.5:3b` (~2.0 GB) and `nomic-embed-text` (~274 MB).
  - SQLite database and Chroma vector store scratch space: ~1.5 GB.
- **Internet connection for the first model pull**: An active internet connection is required solely on the first launch so that Docker Hub images and Ollama models can be pulled. Subsequent runs operate 100% offline with zero external network connectivity.

> [!NOTE]
> **Native Ollama Port Conflict:** Quit native Ollama on that laptop first (from the system tray or by terminating the `ollama` process), or host port `11434` will clash with the containerized Ollama service.

### Exact Steps

#### Step 1: Download Deployment Manifests
On the target laptop, create a project directory and download `docker-compose.hub.yml` and `.env.example`:
```bash
mkdir sovereign-workbench && cd sovereign-workbench

# Download compose file and sample environment configuration
curl -fsSL -o docker-compose.hub.yml https://raw.githubusercontent.com/<YOUR_REPO>/main/docker-compose.hub.yml
curl -fsSL -o .env.example https://raw.githubusercontent.com/<YOUR_REPO>/main/.env.example
```
*(Alternatively, copy `docker-compose.hub.yml` and `.env.example` directly via USB drive or network share).*

#### Step 2: Configure Environment (.env)
Copy `.env.example` to `.env`:
```bash
# Linux / macOS / PowerShell
cp .env.example .env

# Windows Command Prompt
copy .env.example .env
```
Open `.env` in a text editor and set:
1. `DOCKERHUB_USERNAME`: Set to the Docker Hub account or organization where the images are published.
2. `JWT_SECRET_KEY`: Set to a cryptographically secure 256-bit secret string (e.g., generated with `python -c "import secrets; print(secrets.token_hex(32))"` or any 64-character hex string).

> [!IMPORTANT]
> `JWT_SECRET_KEY` is strictly required from `.env`. The Compose specification uses `${JWT_SECRET_KEY:?...}` and provides no default; Docker Compose will refuse to start if this variable is unset or empty.

Example `.env` snippet:
```ini
DOCKERHUB_USERNAME=your_dockerhub_username
TAG=latest
JWT_SECRET_KEY=4a2f8b9e1c3d5a7f6e0b8d2c4e6a8f0b1c3d5e7a9b0c2d4e6f8a0b2c4d6e8f0a
```

#### Step 3: Launch Stack with One Command
Execute Docker Compose to pull the pre-built images and start the services:
```bash
docker compose -f docker-compose.hub.yml up -d
```

#### Step 4: Wait for Models
The bundled one-shot service `ollama-init` will automatically detect when the containerized Ollama engine is healthy and run:
- `ollama pull qwen2.5:3b`
- `ollama pull nomic-embed-text`

You can monitor model pull progress in real time:
```bash
docker compose -f docker-compose.hub.yml logs -f ollama-init
```
When downloads complete, `ollama-init` exits with status `0`. The FastAPI backend will finish its health checks and begin accepting requests.

#### Step 5: Open Web Interface
Open your web browser and navigate to:
- **Streamlit Web UI**: [http://127.0.0.1:8501](http://127.0.0.1:8501)
- **FastAPI Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Backend Health Check**: [http://127.0.0.1:8000/live](http://127.0.0.1:8000/live)

---

### How to Stop and How to Reset

#### Stopping the Stack
- **Pause execution without losing data or models**:
  ```bash
  docker compose -f docker-compose.hub.yml stop
  ```
- **Stop and remove containers (preserving data volumes)**:
  ```bash
  docker compose -f docker-compose.hub.yml down
  ```
  Both named volumes (`sovereign_data` and `sovereign_ollama_data`) remain intact on disk.

#### Resetting the Stack
- **Reset application data only (preserve downloaded model weights)**:
  To wipe SQLite databases, uploaded files, and vector indices while avoiding re-downloading model weights:
  ```bash
  docker compose -f docker-compose.hub.yml down
  docker volume rm sovereign_data
  docker compose -f docker-compose.hub.yml up -d
  ```
- **Complete factory reset (wipe application data AND downloaded model weights)**:
  ```bash
  docker compose -f docker-compose.hub.yml down -v
  ```

---

### Honest Operational Limits
- **CPU-Only Inference Latency**: On a standard laptop without dedicated GPU acceleration, CPU-only local LLM inference is relatively slow. Generating complete agent answers with `qwen2.5:3b` takes approximately **20 to 60 seconds per answer** (depending on context length, chain-of-thought tokens, and agent tool execution turns).
- **Verification in CI Only Unless Proven**: As documented in Section 5, Docker Desktop and WSL2 were not installed on the primary development laptop. Dockerfiles, multi-architecture compilation (`linux/amd64` and `linux/arm64`), and compose orchestration are verified via automated GitHub Actions CI workflows ([.github/workflows/docker-ci.yml](file:///c:/Users/SanjayAnandhakumar/Desktop/FYP/.github/workflows/docker-ci.yml) and [.github/workflows/docker-publish.yml](file:///c:/Users/SanjayAnandhakumar/Desktop/FYP/.github/workflows/docker-publish.yml)) rather than proven locally on this machine.

---

## 4. Offline & Air-Gapped Deployment Procedure

The entire application runtime requires **zero outbound internet connectivity**. Once container images are built, the system can run indefinitely in an air-gapped facility with Wi-Fi and Ethernet completely disconnected.

### Step 1: Build Once on an Connected Machine
In an environment with internet access:
```bash
# Build backend and UI container images
docker compose build
```

### Step 2: Export Images to an Archive Tarball
Export both images using `docker save`:
```bash
docker save -o sovereign-images.tar sovereign-backend:latest sovereign-ui:latest
```

### Step 3: Transfer to Air-Gapped Target Machine
Transfer `sovereign-images.tar` along with the repository files (`docker-compose.yml`, `scripts/`, `.env.example`) to the air-gapped machine via approved offline media (e.g. encrypted USB drive).

### Step 4: Ingest Images on the Offline Machine
On the target machine (with Wi-Fi turned off):
```bash
docker load -i sovereign-images.tar
```

### Step 5: Launch Stack Offline
```bash
# Generate secure JWT secret in .env
python scripts/gen_secret.py --write

# Launch stack without downloading any external layers
docker compose up -d

# Verify full offline operation
python scripts/demo_check.py --password "AirGappedAdmin123!"
```

---

## 5. Empirical Memory Measurements (8 GB Laptop Audit)

All measurements below were obtained on the test machine running genuine Windows 11 with 7.69 GB usable RAM and an Intel 13th Gen CPU with no dedicated GPU.

### Actual Command Execution Audit

#### 1. `docker stats --no-stream` Execution
```powershell
docker stats --no-stream
```
*Exact output recorded:*
```
docker : The term 'docker' is not recognized as the name of a cmdlet, function, script file, or operable program. 
Check the spelling of the name, or if a path was included, verify that the path is correct and try again.
```
*Honest Environment Disclosure*: Docker Desktop and WSL2 were **not installed or executed on the development laptop** (`wsl -l -v` returned: `The Windows Subsystem for Linux is not installed`). All container lifecycle and healthcheck verifications are performed via CI ([.github/workflows/docker-ci.yml](file:///c:/Users/SanjayAnandhakumar/Desktop/FYP/.github/workflows/docker-ci.yml)).

#### 2. Psutil Memory Audit (Measured During Full End-to-End Query Execution)
Measurements recorded using Python's `psutil` library tracking host virtual memory and Ollama processes:

| Lifecycle State | Host Total RAM | Host Used RAM | Host Available RAM | Native Ollama RSS | Backend Uvicorn RSS | Combined Stack Working Set |
|---|---|---|---|---|---|---|
| **Host Baseline (Stack Idle)** | 7.692 GB | 6.569 GB (85.4%) | 1.124 GB | 28.23 MB | 0.0 MB (stopped) | **28.23 MB** |
| **Stack Idle (Uvicorn Active)** | 7.692 GB | 6.715 GB (87.3%) | 0.977 GB | 28.23 MB | 145.62 MB | **173.85 MB** |
| **Active Query Generation** | 7.692 GB | 7.278 GB (94.6%) | 0.414 GB | **2,339.31 MB** | 158.40 MB | **2,497.71 MB** |

> [!NOTE]
> **Measurement Conditions:**
> These RAM figures were measured with the development IDE (Antigravity IDE / VS Code) and browser open on the Windows host (**not a clean, headless baseline**). On a stripped-down headless Windows installation, baseline OS RAM consumption is typically 2.5–3.5 GB rather than ~6.5 GB.

### Memory Analysis & 8 GB RAM Feasibility

> [!WARNING]
> **Memory Pressure Analysis on 8 GB Hosts:**
> 1. When the chat model (`qwen2.5:3b`) and embedding model (`nomic-embed-text`) actively generate answers, Ollama's Resident Set Size (RSS) expands from **28.23 MB** to **2,339.31 MB (~2.34 GB)**.
> 2. With the Windows operating system and active desktop apps consuming ~6.5 GB of RAM during our test, active generation pushed host RAM utilization to **94.6% (7.28 GB / 7.69 GB)**, leaving **414 MB of free physical RAM**.
> 3. **The ~12 GB memory figure is an analytical estimate**: If Docker Desktop / WSL2 were running with default settings (WSL2 dynamically allocates up to 50% of host RAM = ~3.85 GB) alongside native Ollama (2.34 GB) and existing host working sets (~6.5 GB), total theoretical memory demand would reach **12.5 GB**. On an 8 GB physical laptop, this causes heavy paging and disk thrashing unless WSL2 is bounded.

### Recommended `.wslconfig` Memory Cap (Manual Configuration)

To ensure the full stack (Docker + Host Ollama + Windows) operates smoothly without thrashing on an 8 GB laptop, cap WSL2's memory allocation to **2 GB**.

Create or edit the file at `%USERPROFILE%\.wslconfig` (e.g. `C:\Users\<Username>\.wslconfig`):

```ini
# %USERPROFILE%\.wslconfig
[wsl2]
# Cap virtual machine memory to 2 GB to leave 5.7 GB for Windows and host Ollama
memory=2GB

# Provide 4 GB of swap space for burst container compilation
swap=4GB

# Cap CPU cores to prevent lockups during token generation
processors=2
```

After modifying `.wslconfig`, restart WSL from an administrative PowerShell prompt:
```powershell
wsl --shutdown
```

---

## 6. Security & Isolation Verification

| Security Control | Implementation | Verification Method |
|---|---|---|
| **Localhost Port Binding** | `127.0.0.1:8000:8000` & `127.0.0.1:8501:8501` | Non-loopback NICs cannot access container ports. |
| **Non-Root Execution** | UID/GID `10001:10001` (`appuser`) in both Dockerfiles | Containers refuse root escalation. |
| **Required Secret** | `${JWT_SECRET_KEY:?...}` enforced in `docker-compose.yml` | Stack aborts startup if secret is missing or default. |
| **Zero Cloud Egress** | `socket.socket.connect` blocked in `tests/test_stage7_offline.py` | Full test suite passes under 100% network disconnection. |
| **PII Masking** | Regex-based redaction on SSN, credit cards, emails in audit logs | Verified by `tests/test_stage3_security.py`. |
| **Human-in-the-Loop** | Elevated actions (`read_sql`) require supervisor approval | Verified by `tests/test_policy.py`. |

---

## 7. Maintenance & Clean-State Reset Procedure

When re-testing or resetting the development environment to a known baseline:

```powershell
# Reset development state to clean state:
python scripts/reset_dev_state.py

# Or via PowerShell wrapper:
.\scripts\reset_dev_state.ps1
```

### Safety & Integrity Guarantees
1. **Port Check:** Fails if active processes are detected on port 8000 or 8501 to prevent corrupting active sessions (override with `--force`).
2. **Automated Backup:** Copies current `data/` to a timestamped folder `data_backup_YYYYMMDD_HHMMSS/` (git-ignored) prior to any deletion.
3. **Database & Vector Reset:** Completely purges `sovereign.db`, WAL/SHM files, Chroma vector store, uploads, and logs.
4. **Demo Database Re-Seeding:** Recreates `demo.db` with the canonical 10-student dataset and validates row counts and benchmark ground truths.
5. **Preservation:** Never modifies `.env`, `eval/`, `tests/`, `docs/`, or source code.

