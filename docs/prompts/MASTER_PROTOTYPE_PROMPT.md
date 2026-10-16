# MASTER PROMPT: Quick Prototype for "Sovereign On-Premise Agentic AI Workbench"

Paste everything below the line into Antigravity as a single task. Use the Planning mode and let it show the plan before it writes code.

---

## ROLE
You are a senior Python engineer. Build a working, runnable PROTOTYPE of a project called **Sovereign On-Premise Agentic AI Workbench**: a fully offline platform where users upload private documents, create AI agents, chat with them, and see an audit trail of everything the agents do. No data may leave the machine. No cloud APIs.

## HARD CONSTRAINTS (read carefully)
- Target machine: Windows laptop, **8 GB RAM**, no GPU. Memory efficiency matters more than features.
- LLM runtime: **Ollama running natively on the host** at `http://localhost:11434`. Do NOT put Ollama in Docker.
- Models: default chat model comes from env var `OLLAMA_MODEL` (default `mistral`; during development I will set `qwen2.5:3b`). Embedding model: `nomic-embed-text`.
- Use `num_ctx` of 4096 maximum on every Ollama call. Keep retrieved context short (top 3 chunks, about 500 characters each).
- No Docker for this prototype. Run everything natively with a Python virtual environment.
- Allowed libraries only: `fastapi`, `uvicorn`, `sqlalchemy` (SQLite), `chromadb` (embedded persistent client), `streamlit`, `requests` or `httpx`, `pypdf`, `python-docx`, `pydantic`, `python-jose`, `passlib[bcrypt]`, `python-multipart`, `pytest`. Do not add LangChain, LlamaIndex, or any heavy framework. Write the agent loop yourself.
- No external network calls anywhere in the code except to localhost Ollama.
- Keep the code small, readable, and commented. I must be able to explain every file in a viva.

## ARCHITECTURE
```
Streamlit UI  ->  FastAPI backend  ->  Ollama (host)
                      |-- SQLite  (users, agents, runs, steps, audit_logs, documents)
                      |-- Chroma  (embedded, persisted in ./data/chroma)
```

## PROJECT STRUCTURE
```
sovereign-workbench/
  backend/
    main.py            # FastAPI app, routers
    config.py          # env settings
    db.py              # SQLAlchemy models + session
    auth.py            # JWT login, roles (admin, user)
    llm.py             # Ollama client: chat(), embed(), with timeouts
    rag.py             # extract text, chunk, embed, store, retrieve
    agent.py           # agent loop
    tools.py           # tool registry + implementations
    policy.py          # allowlist, role checks, approval, PII masking
    audit.py           # audit logging helper
  ui/
    app.py             # Streamlit app (multi-page via tabs)
  data/                # sqlite file, chroma store, uploads (gitignored)
  tests/
    test_tools.py
    test_policy.py
    test_agent_parsing.py
  requirements.txt
  README.md
  .env.example
```

## FEATURES TO IMPLEMENT (prototype scope)

### 1. Auth and roles
- Register/login with bcrypt-hashed passwords and JWT tokens.
- Two roles: `admin`, `user`. The first registered user becomes admin.
- Admin-only: view all audit logs, create agents, manage users. Users: chat with agents, upload documents.

### 2. Documents and RAG
- Upload PDF, DOCX, or TXT. Extract text, split into chunks (default 500 characters, 50 overlap, configurable), embed with `nomic-embed-text`, store in Chroma with metadata (filename, chunk index).
- Retrieval returns top-k chunks plus source filename and chunk index, so answers can show citations.

### 3. Tools (the registry in `tools.py`)
Each tool has: name, description, JSON argument schema, risk level (`low` or `high`), and a function.
- `search_documents(query)`: RAG retrieval, risk low.
- `calculator(expression)`: safe arithmetic only. Parse with `ast`, allow numbers and `+ - * / ** %` and parentheses. Never use `eval` on raw input. Risk low.
- `read_file(filename)`: read only from `./data/uploads`, reject any path traversal. Risk low.
- `read_sql(query)`: SELECT-only against a small demo SQLite database `data/demo.db` (create a sample `students` table with 10 rows). Reject anything that is not a single SELECT statement. Risk high (needs approval).
Leave a clearly marked placeholder for a future sandboxed Python tool. Do not implement it now.

### 4. Agent loop (`agent.py`), written by hand
- An agent has: name, system prompt, model, allowed tools (list), temperature.
- Loop (max 5 iterations):
  1. Build a prompt containing the system prompt, the descriptions and schemas of the allowed tools only, the conversation, and the strict output format.
  2. Ask the model to reply with ONE JSON object only: either `{"action":"tool","tool":"<name>","args":{...}}` or `{"action":"final","answer":"<text>"}`.
  3. Parse and validate the JSON. If invalid, retry up to 2 times with a short corrective message ("Reply with valid JSON only"). Record each retry in the trace.
  4. For a tool action: pass through the policy layer, execute, append the observation, continue.
  5. On `final`, return the answer plus the list of sources used.
- Small models produce messy output, so make the JSON extraction forgiving: strip code fences, find the first `{` through the last `}`.
- Add a config flag `ENABLE_RETRY` (default true) so I can later turn retries off for an experiment.

### 5. Policy layer (`policy.py`)
Before every tool call, check in this order: (a) tool is in the agent's allowlist, (b) the user's role may use the tool, (c) if the tool is `high` risk, require human approval. In the prototype, approval is a pending record in the DB that the user confirms with a button in the UI; the agent run pauses and resumes after approval or denial. Also mask PII (emails, 10-digit Indian phone numbers, Aadhaar-like 12-digit numbers) in text that is logged. Every decision (allowed, denied, approved) is audit-logged.

### 6. Audit and traces
- `runs` table: one row per agent run (user, agent, question, final answer, status, total latency).
- `steps` table: one row per step (run id, step number, type: llm / tool / retry / policy, input, output, latency ms).
- `audit_logs` table: timestamp, user, action, details, outcome.

### 7. API endpoints
`POST /auth/register`, `POST /auth/login`, `POST /documents/upload`, `GET /documents`, `POST /agents`, `GET /agents`, `POST /agents/{id}/run`, `GET /runs`, `GET /runs/{id}` (with steps), `GET /approvals/pending`, `POST /approvals/{id}/decide`, `GET /audit` (admin), `GET /health` (checks Ollama reachable and models present).
Create two default agents on first start: "Document Assistant" (tools: search_documents, read_file, calculator) and "Data Analyst" (tools: read_sql, calculator).

### 8. Streamlit UI (`ui/app.py`)
Tabs: Login/Register, Chat (pick an agent, ask a question, show answer with citations), Documents (upload and list), Agents (admin: create, edit allowed tools), Traces (list runs, expand to see each step), Approvals (pending high-risk actions with Approve/Deny), Audit Log (admin). Show a small status badge for Ollama health and the active model name. Show a spinner during runs and handle backend errors with a friendly message.

## NON-FUNCTIONAL REQUIREMENTS
- Ollama calls: timeout 120 s, one clear error if Ollama is down.
- Never load a model other than the configured one.
- Never log raw passwords or tokens.
- `requirements.txt` with pinned versions, `.env.example`, `.gitignore` (venv, data/, __pycache__).
- A `README.md` with exact Windows commands: create venv, install, start backend (`uvicorn backend.main:app --port 8000`), start UI (`streamlit run ui/app.py`), and a short troubleshooting section.

## TESTS
Write pytest tests for: calculator (valid expressions and rejection of malicious input such as `__import__('os')`), read_file path traversal rejection, read_sql rejecting non-SELECT, policy allowlist and role denial, PII masking, and the JSON parser on messy model output (fenced, extra text, trailing commas where feasible). Tests must not need Ollama running (mock the LLM).

## ACCEPTANCE CHECKS (do not finish until all pass)
1. `pytest` passes with no Ollama running.
2. `GET /health` reports Ollama status correctly.
3. Register the first user, confirm they are admin; log in; upload a TXT file; ask the Document Assistant a question about it; the answer shows a citation.
4. Ask the Data Analyst a question that needs `read_sql`; the run pauses for approval; after approving in the UI the answer is returned; the denial path also works.
5. The Traces tab shows every step with latency, and the Audit tab shows the policy decisions.
6. With the network disconnected, everything above still works.

## WORKING STYLE
1. First show a short plan and the file list. Then implement in this order: db/config/auth, llm, rag, tools, policy and audit, agent, API, UI, tests, README.
2. After each group, run it or the relevant tests and fix errors before moving on.
3. Do not invent features outside this scope. If something is ambiguous, choose the simpler option and note it in README under "Design decisions".
4. At the end, print: how to run, what works, what is stubbed, and any known limitations.
