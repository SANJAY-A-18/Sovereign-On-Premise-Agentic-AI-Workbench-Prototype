# Sovereign On-Premise Agentic AI Workbench

A fully offline, privacy-first, on-premise agentic AI workbench. Users can securely upload private documents, create and configure AI agents, interact with them using local LLMs, and inspect a full governance and audit trail of every tool invocation and policy decision.

**Zero data leaves the machine. No cloud APIs. Strict offline execution.**

---

## Architecture Overview

```
Streamlit UI (Port 8501)
         │
         ▼ (HTTP / REST)
FastAPI Backend (Port 8000) ──────► Host Ollama (http://localhost:11434)
         │                                (Native process, qwen2.5:3b, num_ctx <= 4096)
         ├──► SQLite (./data/sovereign.db) [WAL mode, 30s busy timeout]
         │      ├── Users (Role: admin, user; min 6-char password, bcrypt hashed)
         │      ├── Agents (Custom system prompts, temperature 0.0-1.0, tool allowlists)
         │      ├── Runs & Steps (Step-by-step trace & latencies, fail-safe status)
         │      ├── Approvals (Human-in-the-loop pending actions, owner-scoped)
         │      ├── Audit Logs (PII masked security audit trail, filterable)
         │      └── Documents (Metadata for ingested files, delete with vector cleanup)
         │
         ├──► ChromaDB (./data/chroma)
         │      └── Persistent local vector store with nomic-embed-text (telemetry disabled)
         │
         └──► Demo SQLite DB (./data/demo.db)
                └── Read-only sample 'students' table for read_sql queries
```

---

## Hardware & System Constraints

- **Host Machine:** Windows laptop, **8 GB RAM budget**, no dedicated GPU required.
- **LLM Runtime:** Host native **Ollama** running at `http://localhost:11434` (Ollama runs natively outside Docker for optimal memory footprint).
- **Default Configured Models:**
  - Chat Model: **`qwen2.5:3b`** (~1.9 GB VRAM/RAM footprint).
  - Embedding Model: **`nomic-embed-text`** (~274 MB footprint).
- **Context Window:** Capped strictly to **4096 tokens (`num_ctx: 4096`)** on every Ollama request to prevent out-of-memory errors on 8 GB laptops.
- **Retrieval Budget:** Top **3 chunks** (~500 chars with 50 char overlap) per query.
- **Network Isolation:** 100% offline runtime. Socket non-loopback connections prohibited. Zero cloud telemetry.

---

## Setup & Running on Windows (Exact Commands)

### 1. Prerequisites
- **Python 3.11** installed on Windows.
- **Ollama** installed on Windows host:
  - Download from [ollama.com](https://ollama.com)
  - Pull the two required sovereign models in PowerShell:
    ```powershell
    ollama pull qwen2.5:3b
    ollama pull nomic-embed-text
    ```

### 2. Create Virtual Environment & Install Dependencies
Open **PowerShell** in the project repository root:

```powershell
# Create Python 3.11 virtual environment
python -m venv .venv

# Activate the virtual environment
.\.venv\Scripts\activate

# Install pinned dependencies
python -m pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```
Default `.env` configuration:
```ini
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_EMBED_MODEL=nomic-embed-text
OLLAMA_NUM_CTX=4096
JWT_SECRET_KEY=sovereign-workbench-local-offline-secret-key-2026
```

### 4. Running the Applications

#### Start the FastAPI Backend (Port 8000)
In the first PowerShell window:
```powershell
.\.venv\Scripts\activate
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
- API Documentation: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

#### Start the Streamlit Web UI (Port 8501)
In a second PowerShell window:
```powershell
.\.venv\Scripts\activate
streamlit run ui/app.py --server.port 8501
```
- Open browser at `http://localhost:8501`

---

## Testing & Verification

### Run Automated Unit and Integration Tests (Fast, 100% Offline)
```powershell
.\.venv\Scripts\pytest -m "not live"
```
**Test Count:** **65 passed tests** covering:
- Agent JSON parsing, repair, and normalization (`tests/test_agent_parsing.py`)
- API endpoints & security contracts (`tests/test_api.py`)
- Policy engine & role permissions (`tests/test_policy.py`)
- Safe tools & sandboxing (`tests/test_tools.py`)
- Stage 2 Feature Audit (`tests/test_stage2_audit.py`)
- Stage 3 Security, SQLi/traversal fuzzing, & PII masking (`tests/test_stage3_security.py`)
- Stage 4 Robustness, Ollama crash recovery, concurrency, & WAL (`tests/test_stage4_robustness.py`)
- Stage 7 Offline proof & loopback socket guard (`tests/test_stage7_offline.py`)
- Stage 6 Streamlit AppTest UI verification (`tests/test_ui_comprehensive.py`, `tests/test_ui_smoke.py`)

### Run Live End-to-End Tests against Real Ollama
Requires Ollama running locally with `qwen2.5:3b` and `nomic-embed-text`:
```powershell
.\.venv\Scripts\pytest -m "live"
```

### Run Live Verification Script (`scripts/live_check.py`)
Verifies full end-to-end integration against active backend:
```powershell
# In a separate terminal with backend running:
python scripts/live_check.py
```

### Run Regression Suite (`scripts/run_regression_suite.py`)
Executes the 15 regression prompts across document facts, unanswerable queries, math, SQL, edge phrasing, and multi-step reasoning:
```powershell
python -u scripts/run_regression_suite.py docs/regression_results.json
```

---

## Memory & Performance Metrics (Measured on 8 GB Laptop)

| Component | Working Set (RAM) | Details |
|---|---|---|
| Native Ollama Engine | ~35 MB idle | C++ native runtime |
| `qwen2.5:3b` Model | ~1,840 MB active | Q4_K_M 4-bit quantized |
| `nomic-embed-text` | ~274 MB active | F16 context 2048 embeddings |
| FastAPI Backend | ~85 MB | Starlette + SQLAlchemy + SQLite WAL |
| Streamlit UI | ~95 MB | Local web interface |
| Embedded ChromaDB | ~120 MB | In-process native vector index |
| **Total System RAM** | **~2.45 GB** | **Well within 8 GB laptop budget (< 35% utilization)** |

---

## Repository Structure

```
.
├── backend/                  # FastAPI backend and core sovereign engine
│   ├── agent.py              # Hand-crafted agent loop with fail-safe status & retries
│   ├── auth.py               # JWT authentication & bcrypt password hashing
│   ├── config.py             # Centralized settings & offline telemetry suppression
│   ├── db.py                 # SQLite database models, WAL pragmas, & SessionLocal
│   ├── llm.py                # Native Ollama client (timeout 120s, num_ctx <= 4096)
│   ├── main.py               # FastAPI application, REST endpoints, CORS & exception filters
│   ├── policy.py             # Human-in-the-loop policy engine & PII regex maskers
│   ├── rag.py                # Text extraction (PDF, DOCX, TXT), chunker & ChromaDB
│   └── tools.py              # Sandboxed tools (search_documents, calculator, read_sql, read_file)
├── ui/
│   └── app.py                # Streamlit Web UI (Sovereign Dark Glassmorphism, role-scoped tabs)
├── docs/
│   ├── DESIGN_NOTES.md       # Architecture, agent loop, bug postmortems, & known limitations
│   ├── FEATURE_MATRIX.md     # Feature-by-feature verification matrix
│   ├── regression_results_before.json # Baseline regression run results
│   ├── regression_results_after.json  # Hardened regression run results (93.3% accuracy)
│   └── prompts/              # Prompt references (MASTER_PROTOTYPE_PROMPT.md)
├── scripts/
│   ├── live_check.py         # End-to-end live backend verification script
│   └── run_regression_suite.py # 15-prompt regression suite runner
├── tests/                    # 67 comprehensive unit & integration tests
├── .env.example              # Environment variable template with placeholders
├── pytest.ini                # Pytest configuration and live/offline markers
└── requirements.txt          # Pinned dependency manifest
```
