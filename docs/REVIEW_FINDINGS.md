# Repository Review Findings: Sovereign Agentic AI Workbench

**Date:** Post-Evaluation Verification (Fixes Branch, Baseline `eval-v1`)  
**Scope:** Error handling & timeouts, input validation, file uploads & sanitization, JWT/secret safety, CORS, sensitive data logging, resource cleanup, Streamlit session state, dead code/unused imports, requirements pinning, Dockerfile practices, and documentation accuracy.

---

## 1. Executive Summary

A comprehensive repository audit identified **2 HIGH**, **4 MEDIUM**, and **4 LOW** severity findings. In accordance with the project guidelines:
- All **HIGH** and **MEDIUM** findings have been remediated with root-cause code fixes and verified with regression tests.
- All **LOW** findings are documented below for operator awareness.
- No architectural changes or modifications to frozen evaluation paths were made.

| Severity | Count | Status |
|---|---|---|
| **HIGH** | 2 | **Resolved** (Code fixed + regression tests added) |
| **MEDIUM** | 4 | **Resolved** (Code fixed + regression tests added) |
| **LOW** | 4 | **Documented** (Listed for review) |

---

## 2. HIGH Severity Findings (Resolved)

### Finding H-1: Document Upload Vector Ingestion Failure Leaves Corrupted DB Record & Leaked Disk File
- **Component:** `backend/main.py:426-444` (`upload_document`)
- **Category:** Resource Cleanup & Transactional Consistency
- **Description:** When an authenticated user uploads a file (`.txt`, `.pdf`, `.docx`), the file is written to `./data/uploads/` and committed to SQLite (`Document` record). Next, `vector_store.add_document()` embeds the chunks via Ollama and stores them in ChromaDB. If vector embedding raises an exception (e.g. Ollama service unavailable, timeout, or model failure), the handler caught the error, logged an audit event, and raised an HTTP 500. However, the committed SQLite `Document` record was **never deleted**, and the uploaded file on disk was **never unlinked**.
- **Impact:** The system was left in a corrupt state: the document existed in the database with 0 indexed vector chunks in Chroma. Because duplicate upload checks prevent uploading a file with an already existing name (`existing = db.query(Document).filter(...)`), the user was permanently blocked from re-uploading the file until an admin manually purged the database.
- **Remediation:** In the `except Exception as e:` block of `vector_store.add_document()`, the database transaction deletes `doc_record` (`db.delete(doc_record); db.commit()`) and deletes the file from disk (`save_dest.unlink()`).
- **Verification:** Unit and API regression test verifying that a simulated embedding failure rolls back the database record, unlinks the file on disk, and allows subsequent re-upload.

---

### Finding H-2: Uncaught Exceptions in Backend Agent Execution Could Leave Runs Orphaned in `running` State
- **Component:** `backend/main.py:772` (`run_agent`) and `backend/agent.py:530-560` (`AgentRunner.run_agent`)
- **Category:** Error Handling & State Resilience
- **Description:** While Ollama HTTP errors were caught and handled inside the agent loop, any unexpected runtime exception (e.g. database connection drop, unexpected serialization failure, or unhandled tool exception) could escape out of the agent runner. If this occurred during `POST /agents/{id}/run`, the run record in SQLite remained permanently in `status = "running"`.
- **Impact:** Users received a generic 500 error while the run was marked active indefinitely. Because active-run concurrency guards reject new questions matching an active run (`Run.status.in_(["running", "paused_for_approval"])`), the user was locked out of re-running the same query until backend restart.
- **Remediation:** Ensured `run_agent` in `backend/main.py` wraps `AgentRunner.run_agent` with an explicit fail-safe handler: if an unhandled exception occurs, `run.status` is set to `"failed"`, `run.final_answer` records the error detail, the transaction is committed, and clean error details are returned.
- **Verification:** Verified via robustness test triggering unexpected execution failure; confirmed run status transitions to `failed` and allows immediate subsequent user runs.

---

## 3. MEDIUM Severity Findings (Resolved)

### Finding M-1: SQLite WAL Mode and Busy Timeout Not Re-Applied Upon `reset_db_engine()`
- **Component:** `backend/db.py:180-188` (`reset_db_engine`)
- **Category:** Concurrency & Resource Configuration
- **Description:** The SQLite event listener (`@event.listens_for(engine, "connect")`) configuring `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=30000` was registered exclusively on the module-level `engine` instance. When `reset_db_engine()` was invoked (e.g. during test setup or dynamic configuration), a new SQLAlchemy `engine` was instantiated, but the event listener was not attached to the new engine.
- **Impact:** Any database operations executed after `reset_db_engine()` reverted to SQLite's default rollback journal with zero busy timeout, drastically increasing the likelihood of `sqlite3.OperationalError: database is locked` during concurrent requests.
- **Remediation:** Added `event.listen(engine, "connect", set_sqlite_pragma)` inside `reset_db_engine()` so that newly initialized engines always configure WAL mode and a 30-second busy timeout.
- **Verification:** Verified via multi-threaded concurrent query test across engine reset.

---

### Finding M-2: Default / Insecure `JWT_SECRET_KEY` Loaded Without Operator Warning
- **Component:** `backend/main.py:lifespan` and `backend/config.py`
- **Category:** Secret & Default Configuration Safety
- **Description:** When the `.env` file is missing or `JWT_SECRET_KEY` is omitted, the configuration defaults to `"sovereign-workbench-local-offline-secret-key-2026"`. While `scripts/gen_secret.py` flags this string as insecure, the backend server previously started without logging any warning to the administrator.
- **Impact:** An operator running the workbench without reading the deployment guide could run in production with a well-known secret key, vulnerable to token spoofing if LAN access is obtained.
- **Remediation:** In `backend/main.py:lifespan`, added an inspection check on startup: if `settings.JWT_SECRET_KEY` matches known defaults or is shorter than 32 characters, an explicit `uvicorn.error` security warning is logged prompting the operator to run `python scripts/gen_secret.py --write`.
- **Verification:** Tested backend startup with default key; confirmed warning appears in console logs.

---

### Finding M-3: Document Upload Filename Sanitization Did Not Strip URL Encoding or Reject Hidden Files
- **Component:** `backend/main.py:361` (`upload_document`)
- **Category:** Input Validation & Filename Sanitization
- **Description:** Filename sanitization relied solely on `safe_filename = Path(file.filename).name`. Client payloads containing URL-encoded characters (e.g. `%2e%2e%2fmalicious.txt`) or hidden file prefixes (e.g. `.env`, `.git/config`) were not properly decoded or rejected.
- **Impact:** Potential for confusing file paths or unintended storage of hidden configuration files in `./data/uploads/`.
- **Remediation:** Added `urllib.parse.unquote()` before path resolution and added strict rejection of hidden files (`safe_filename.startswith(".")`) and empty filenames.
- **Verification:** Fuzzing with URL-encoded paths and hidden filenames verified rejected with HTTP 400.

---

### Finding M-4: Approvals Tab Rendered Lingering Decision Banner Across Sessions
- **Component:** `ui/app.py:832-835`
- **Category:** Streamlit State Lifecycle
- **Description:** In the Streamlit UI, when an administrator approved or denied a request, `st.session_state["last_approval_decision"]` was populated to show a notification banner. However, this banner had no dismiss control and lingered indefinitely across unrelated operations until page reload.
- **Impact:** Stale decision messages remained visible long after the corresponding run had concluded.
- **Remediation:** Added a dismissal button `✖ Dismiss` adjacent to the banner, allowing users to clear the notification, and ensured `last_approval_decision` is reset whenever the user logs out or switches agents.
- **Verification:** Verified in AppTest that clicking dismiss resets the session state key and clears the banner.

---

## 4. LOW Severity Findings (Documented for Operator Review)

### Finding L-1: Use of Deprecated `datetime.utcnow()`
- **Component:** `backend/auth.py`, `backend/db.py`, `backend/audit.py`
- **Description:** Python 3.12+ deprecates `datetime.utcnow()` in favor of timezone-aware `datetime.now(timezone.utc)`.
- **Operator Action:** No immediate action required on Python 3.11 runtime; planned for future Python 3.12+ modernization.

### Finding L-2: `requirements-eval.txt` Uses Unpinned Dependency
- **Component:** `requirements-eval.txt:1`
- **Description:** `requirements.txt` strictly pins all runtime dependencies with exact versions (`==`). In contrast, `requirements-eval.txt` specifies `matplotlib>=3.8.0`.
- **Operator Action:** For strict build reproducibility, `requirements-eval.txt` can be pinned to `matplotlib==3.11.2`.

### Finding L-3: Minor Unused Imports in Scripts and Evaluation Modules
- **Component:** `eval/report.py`, `scripts/gen_secret.py`, `scripts/reset_dev_state.py`
- **Description:** A static AST audit identified minor unused standard library imports (e.g. `import os` in scripts that utilize `pathlib.Path`).
- **Operator Action:** Cosmetic only; zero runtime impact. Cleaned up where practical.

### Finding L-4: Documentation Discrepancies in Test and File Counts
- **Component:** `README.md:243, 321`
- **Description:** `README.md` references 119 unit tests and 74 test cases from an earlier development iteration. Following the addition of lifecycle and regression suites, the suite contains 123+ tests.
- **Operator Action:** Updated during the README pass in Phase 2.
