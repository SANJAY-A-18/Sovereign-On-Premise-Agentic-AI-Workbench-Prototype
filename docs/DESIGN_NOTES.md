# Architecture & Design Notes: Sovereign On-Premise Agentic AI Workbench

## 1. System Architecture

The Sovereign On-Premise Agentic AI Workbench is engineered for zero-cloud-egress on an 8 GB RAM laptop running Windows. The architecture consists of three standalone layers:

```
+-------------------------------------------------------------+
|                      Streamlit Web UI                       |
|   (Port 8501: Role-scoped tabs, glassmorphism, approvals)   |
+------------------------------+------------------------------+
                               | REST / JSON
                               v
+-------------------------------------------------------------+
|                      FastAPI Backend                        |
|   (Port 8000: Auth, RBAC, Policy Engine, Agent Loop, RAG)   |
+--------------+---------------+--------------+---------------+
               |               |              |
               v               v              v
      +-----------------+ +----------+ +------------------+
      |  Native Ollama  | | SQLite   | | Embedded Chroma  |
      |   (:11434)      | | (WAL)    | | (Persistent)     |
      | qwen2.5:3b      | | Data &   | | Vector Store     |
      | nomic-embed     | | Demos    | | nomic-embed-text |
      +-----------------+ +----------+ +------------------+
```

### Key Architectural Boundaries
1. **Host-Native Ollama LLM (`http://localhost:11434`):**
   - Direct HTTP communication via `httpx.Client` without LangChain or LlamaIndex.
   - Enforces `num_ctx <= 4096` and a strict 120-second timeout.
   - No external API keys, tokens, or cloud endpoints.
2. **Persistence with SQLite WAL Mode (`sovereign.db` & `demo.db`):**
   - Standard SQLite database accessed via SQLAlchemy with `timeout=30.0` and PRAGMA `journal_mode=WAL` + `busy_timeout=30000`.
   - Prevents `database is locked` errors during concurrent tool execution or rapid user clicks.
3. **Embedded ChromaDB (`data/chroma`):**
   - In-process native vector index persisted to disk.
   - Telemetry strictly disabled via `anonymized_telemetry=False`, `Posthog.capture = lambda *args, **kwargs: None`, and environment variables `ANONYMIZED_TELEMETRY=False` and `CHROMA_TELEMETRY=False`.

---

## 2. Hand-Crafted Agent Loop

The agent loop (`backend/agent.py`) is written from scratch without heavy agentic frameworks.

### Loop Progression
1. **Prompt Synthesis:** Builds system instruction detailing agent identity, allowed tool schemas, operating schemas (Schema A for tools, Schema B for final answers), and explicit rules for math (`calculator`), database tables (`read_sql`), and document knowledge (`search_documents`).
2. **Inference Call:** Queries Ollama with `format="json"`, temperature, and context limit <= 4096.
3. **Forgiving JSON Extraction & Normalization:**
   - Strips conversational preamble and markdown code fences (````json ... ````).
   - Fixes trailing commas before `}` or `]`.
   - Normalizes tool parameters (`query`, `expression`, `file_path`) while preserving original keys.
4. **Retry Logic (`ENABLE_RETRY`):**
   - If JSON decoding fails, generates a corrective prompt and re-queries Ollama at lower temperature (0.1).
   - Up to 2 retries when `ENABLE_RETRY=True`; fails fast when `ENABLE_RETRY=False`.
5. **Fail-Safe Execution Guarantee:**
   - Top-level `try...except` wrapper ensures `run.status = "failed"` is committed to the database upon any unhandled exception, ensuring no run ever remains stuck in `"running"`.
   - Server startup `lifespan` automatically scans and marks any orphaned `"running"` runs as failed.

---

## 3. Policy & Human-in-the-Loop Approval Flow

### Policy Evaluation Layer (`backend/policy.py`)
Every tool invocation is intercepted before execution:
1. **Allowlist Verification:** Tool must be explicitly declared in the Agent's `allowed_tools` JSON array. Unauthorized tools are `DENIED`.
2. **Role-Based Access Control:** High-risk actions (such as `read_sql` or sandbox executions) require admin rights or supervisor approval.
3. **Human-in-the-Loop Pause & Resume:**
   - High-risk tool invocation halts the agent loop and creates an `Approval` record with status `pending`.
   - The run transitions to `status = "paused_for_approval"`.
   - Admin or run owner inspects tool name and arguments in `/approvals/pending` or the UI Approvals tab.
   - Deciding `approve`: The backend executes the approved tool, records the observation in `steps`, and resumes the agent loop.
   - Deciding `deny`: The backend injects a supervisor denial observation, and the agent adapts or formulates a final answer.
   - State persists across backend restarts: paused runs remain resumable upon server reboot.

---

## 4. PII and Credential Masking Points

Sensitive data is masked before logging or trace persistence (`backend/policy.py:mask_pii`), ensuring compliance while preserving the user's visible response:
- **Email Addresses:** Masked to `[EMAIL_MASKED]` via regex `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b`.
- **10-Digit Indian Mobile Numbers:** Masked to `[PHONE_MASKED]` via regex `\b[6-9]\d{9}\b`.
- **12-Digit Aadhaar-like IDs:** Masked to `[AADHAAR_MASKED]` via regex `\b\d{4}\s\d{4}\s\d{4}\b` and `\b\d{12}\b`.
- **Credentials & Tokens:** Password hashes, JWT tokens, and Bearer strings are excluded from audit logs, step outputs, and approval arguments.

---

## 5. Major Defects Found, Root Causes, and Fixes

### Defect 1: Agent Run Stuck in "Running" on Unhandled Exception (Severity: P0)
- **Root Cause:** If Ollama threw a connection error or unexpected runtime exception outside the inner chat block, `run.status` was never updated in SQLite, leaving runs permanently stuck in `running`.
- **Fix:** Refactored `AgentRunner.run_agent` to wrap loop execution in a top-level `try...except` block that commits `run.status = "failed"` and records the exception in `run.final_answer`. Added startup recovery in `lifespan` to mark orphaned runs as failed.
- **Test Added:** `tests/test_stage4_robustness.py::test_ollama_stopped_mid_run_marks_failed` and `test_lifespan_cleans_orphaned_running_runs`.

### Defect 2: Weak Tool Invocation by Smaller Models on SQL and RAG (Severity: P1)
- **Root Cause:** The 3B model (`qwen2.5:3b`) lacked explicit operating rules instructing it that questions regarding database tables require `read_sql` and questions on specifications require `search_documents`, causing it to output hypothetical queries in text rather than calling the tool.
- **Fix:** Added explicit Rules 8 and 9 in `build_system_prompt` and expanded parameter normalization in `validate_agent_action` for `read_sql` and `read_file`.
- **Verification:** Regression accuracy improved from 40.0% (6/15) to 93.3% (14/15) with 100% first-try JSON validity on real Ollama.

### Defect 3: SQLite Database Locking Under Concurrent Requests (Severity: P1)
- **Root Cause:** Default SQLite configuration on Windows operated with short 5-second busy timeouts and standard rollback journal, raising `OperationalError: database is locked` under simultaneous queries or rapid clicks.
- **Fix:** Configured `connect_args={"check_same_thread": False, "timeout": 30.0}` and attached an engine connect listener executing `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=30000`.
- **Test Added:** `tests/test_stage4_robustness.py::test_rapid_repeated_clicks_blocked`.

### Defect 4: Insecure Wildcard CORS with Credentials (Severity: P0)
- **Root Cause:** `CORSMiddleware` was initialized with `allow_origins=["*"]` alongside `allow_credentials=True`, violating modern web security standards.
- **Fix:** Restricted CORS to explicit local origins: `http://localhost:8501`, `http://127.0.0.1:8501`, `http://localhost:8000`, `http://127.0.0.1:8000`.
- **Test Added:** `tests/test_stage3_security.py::test_cors_configuration`.

### Defect 5: Object-Level Authorization Bypasses on Documents and Approvals (Severity: P0)
- **Root Cause:** `DELETE /documents/{id}`, `GET /approvals/pending`, and `POST /approvals/{id}/decide` lacked user ownership checks, allowing any authenticated user to delete another user's documents or decide approvals for other users' runs.
- **Fix:** Enforced object-level checks requiring either admin role or ownership matching `document.uploaded_by == current_user.id` and `run.user_id == current_user.id`.
- **Test Added:** `tests/test_stage3_security.py::test_object_level_authorization`.

---

## 6. Known Limitations & Recommendations for Evaluation Module

1. **Host Ollama Concurrency:** Native Ollama on an 8 GB laptop runs models serially in RAM/VRAM. When multiple concurrent requests hit the model simultaneously, requests queue in Ollama; sustained back-to-back heavy prompts can cause temporary timeouts (as observed during prompt #12 in high-load testing).
2. **Browser Driver Environment:** Native Playwright binaries cannot be downloaded dynamically in strict air-gapped environments without pre-bundled browser caches. The web UI is verified via `streamlit.testing.v1.AppTest`.
3. **Complex Multi-Step Tool Chaining:** On 3B parameter models, multi-step tasks requiring more than 2 sequential tool invocations (e.g. database query -> calculation -> document search) can occasionally stop early with a partial summary. Future evaluation should assess prompting enhancements or fine-tuned system instructions.

---

## 7. Post-Evaluation Architecture Decisions & Robustness Hardening

### 7.1 Shared Institutional Knowledge Base vs. Object-Level Isolation
A fundamental design consideration during post-evaluation was whether uploaded documents should be completely private to individual users or shared across the institution:
- **Intended Design (Shared Knowledge Base):** In an enterprise or university deployment, uploaded policies, regulations, and handbooks constitute shared institutional knowledge. All authorized AI agents (e.g. Document Assistant) and authenticated users query the collective vector repository to provide accurate institutional grounding.
- **Strict Object-Level Authorization:** To protect data integrity without sacrificing shared retrieval:
  1. **Document Modification & Deletion:** Enforced via `DELETE /documents/{id}` and UI permission checks: regular users can only delete documents they personally uploaded (`document.uploaded_by == current_user.id`); administrators can delete any document. Other users see read-only badges (`🔒 Shared`).
  2. **Run & Execution Trace Isolation:** Users can only query their own runs (`GET /runs` strictly filters `user_id == current_user.id`) and traces (`GET /runs/{id}` returns HTTP 403 Forbidden for other users' traces).
  3. **Human Approval Scoping:** Only run owners or administrators can inspect pending approvals or decide high-risk tool execution (`GET /approvals/pending` and `POST /approvals/{id}/decide`).
  4. **Security Audit Log Isolation:** Audit trails containing sensitive compliance logs (`GET /audit`) are strictly restricted to the `admin` role (HTTP 403 for regular users).
- **Verification:** Tested in `tests/test_stage3_security.py::test_object_level_authorization` and `tests/test_ui_comprehensive.py::test_ui_documents_shared_kb_and_authorization`.

### 7.2 Pre-Approval Static SQL Validation
Before creating a human-in-the-loop approval request for `read_sql`:
1. The backend runs static AST/keyword checks (single statement, SELECT only, no comment bypasses).
2. It executes an `EXPLAIN <query>` statement using a read-only SQLite connection against `demo.db`.
3. If the query references non-existent tables or columns, or contains invalid syntax, the policy engine rejects the query with `PolicyDecision.DENIED` and immediately returns the error along with the active SQLite schema (`students (id, name, department, marks, gpa, graduation_year)`) to the agent without requiring human supervisor intervention.

### 7.3 Duplicate Tool Loop Prevention
To eliminate infinite retry loops on local models:
- The agent loop tracks call signatures `(tool_name, frozenset(args))`.
- If an agent attempts an identical tool call that previously failed or was denied, execution is intercepted, a policy step is logged, and the loop forces the model to synthesize a final answer or explain the limitation to the user.

### 7.4 Clean-State Reset Lifecycle (`scripts/reset_dev_state.py`)
Provides automated, deterministic developer state reset:
- Fails safe if servers are active on ports 8000/8501 (unless `--force`).
- Creates timestamped backups (`data_backup_YYYYMMDD_HHMMSS/`) ignored by Git.
- Purges `sovereign.db`, WAL/SHM, Chroma vectors, uploads, and logs.
- Re-seeds `demo.db` with canonical 10-student records, asserting row counts and benchmark ground truth answers.

