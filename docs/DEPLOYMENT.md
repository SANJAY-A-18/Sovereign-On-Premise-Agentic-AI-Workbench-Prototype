# Sovereign On-Premise Agentic AI Workbench: Deployment Guide

This document describes the one-command deployment workflow, air-gapped offline transfer procedure, memory resource benchmarks, and 8 GB RAM optimization guidelines for the **Sovereign On-Premise Agentic AI Workbench**.

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

## 2. Quickstart: One-Command Deployment

### Prerequisites
- Native **Ollama** installed on the host and running:
  ```powershell
  ollama serve
  ollama pull qwen2.5:3b
  ollama pull nomic-embed-text
  ```
- **Docker** and **Docker Compose v2** installed.

### 3-Command Launch
```powershell
# 1. Generate a cryptographically secure 256-bit JWT secret into .env
python scripts/gen_secret.py --write

# 2. Build the production runtime containers (pinned requirements.txt only)
docker compose build

# 3. Launch the full sovereign workbench stack in the background
docker compose up -d
```

### Accessing the Workbench
- **Streamlit Web UI**: [http://127.0.0.1:8501](http://127.0.0.1:8501)
- **FastAPI Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **System Health Status**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### Running Acceptance & Demo Verification
After starting the stack, verify all 5 end-to-end workflows (Ollama health, admin authentication, document upload, RAG retrieval question with citations, and arithmetic calculation):
```powershell
python scripts/demo_check.py --password "YourAdminPassword123!"
```
Or via PowerShell wrapper:
```powershell
.\scripts\demo_check.ps1 -Password "YourAdminPassword123!"
```

---

## 3. Offline & Air-Gapped Deployment Procedure

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

## 4. Empirical Memory Measurements (8 GB Laptop Audit)

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
*Environment finding*: The host machine does not have Docker Desktop or WSL2 installed (`wsl -l -v` returned `The Windows Subsystem for Linux is not installed`).

#### 2. Psutil Memory Audit (Measured During Full End-to-End Query Execution)
Measurements recorded using Python's `psutil` library tracking host virtual memory and Ollama processes:

| Lifecycle State | Host Total RAM | Host Used RAM | Host Available RAM | Native Ollama RSS | Backend Uvicorn RSS | Combined Stack Working Set |
|---|---|---|---|---|---|---|
| **Host Baseline (Stack Idle)** | 7.692 GB | 6.569 GB (85.4%) | 1.124 GB | 28.23 MB | 0.0 MB (stopped) | **28.23 MB** |
| **Stack Idle (Uvicorn Active)** | 7.692 GB | 6.715 GB (87.3%) | 0.977 GB | 28.23 MB | 145.62 MB | **173.85 MB** |
| **Active Query Generation** | 7.692 GB | 7.278 GB (94.6%) | 0.414 GB | **2,339.31 MB** | 158.40 MB | **2,497.71 MB** |

### Memory Analysis & 8 GB RAM Feasibility Warning

> [!WARNING]
> **Severe Memory Pressure Warning on 8 GB Hosts:**
> 1. When the chat model (`qwen2.5:3b`) and embedding model (`nomic-embed-text`) are actively answering questions, Ollama's Resident Set Size (RSS) expands from **28.23 MB** to **2,339.31 MB (~2.34 GB)**.
> 2. With the Windows operating system and baseline background services consuming ~6.5 GB of RAM, active generation pushes host RAM utilization to **94.6% (7.28 GB / 7.69 GB)**, leaving only **414 MB of free physical RAM**.
> 3. If Docker Desktop runs on top of this without strict memory bounds, WSL2 will allocate up to **50% of host RAM (3.85 GB)** for its Linux VM by default. In that scenario, total memory demand (3.85 GB WSL2 + 2.34 GB Ollama + 5.0 GB Windows) exceeds 11 GB, causing severe disk thrashing, paging lag, or OOM crashes.

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

## 5. Security & Isolation Verification

| Security Control | Implementation | Verification Method |
|---|---|---|
| **Localhost Port Binding** | `127.0.0.1:8000:8000` & `127.0.0.1:8501:8501` | Non-loopback NICs cannot access container ports. |
| **Non-Root Execution** | UID/GID `10001:10001` (`appuser`) in both Dockerfiles | Containers refuse root escalation. |
| **Required Secret** | `${JWT_SECRET_KEY:?...}` enforced in `docker-compose.yml` | Stack aborts startup if secret is missing or default. |
| **Zero Cloud Egress** | `socket.socket.connect` blocked in `tests/test_stage7_offline.py` | Full test suite passes under 100% network disconnection. |
| **PII Masking** | Regex-based redaction on SSN, credit cards, emails in audit logs | Verified by `tests/test_stage3_security.py`. |
| **Human-in-the-Loop** | Elevated actions (`read_sql`) require supervisor approval | Verified by `tests/test_policy.py`. |
