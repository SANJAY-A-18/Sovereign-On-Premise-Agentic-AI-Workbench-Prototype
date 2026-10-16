"""
Stage 2 Feature-by-Feature Functional Audit Test Suite.
Validates all requirements from MASTER_PROTOTYPE_PROMPT.md:
Auth, Documents, Tools, Agent Loop, Policy, Approvals, Traces, Audit, Admin, and Health.
"""

from datetime import timedelta
import io
import json
from pathlib import Path
from unittest.mock import patch

import docx
import pypdf
import pytest
from starlette.testclient import TestClient

from backend.config import EMBEDDING_DIM, settings
from backend.db import Base, get_db
from backend.main import app, seed_default_agents
from backend.tools import calculator, read_file, read_sql
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# Shared in-memory test database for the audit suite
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def audit_client():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()
    try:
        seed_default_agents(db)
    finally:
        db.close()

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ==============================================================================
# 1. AUTH TESTS
# ==============================================================================

def test_auth_full_matrix(audit_client):
    # First user must be admin
    r1 = audit_client.post("/auth/register", json={"username": "alice_admin", "password": "Password123!"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["role"] == "admin"
    admin_token = d1["access_token"]

    # Second user must be normal user
    r2 = audit_client.post("/auth/register", json={"username": "bob_user", "password": "Password123!"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["role"] == "user"
    user_token = d2["access_token"]

    # Duplicate username rejection
    r_dup = audit_client.post("/auth/register", json={"username": "alice_admin", "password": "Password123!"})
    assert r_dup.status_code == 400
    assert "already registered" in r_dup.json()["detail"]

    # Empty username or password
    r_empty = audit_client.post("/auth/register", json={"username": "", "password": "Password123!"})
    assert r_empty.status_code == 400
    r_empty_p = audit_client.post("/auth/register", json={"username": "charlie", "password": "   "})
    assert r_empty_p.status_code == 400

    # Very short password (< 6 chars)
    r_short = audit_client.post("/auth/register", json={"username": "charlie", "password": "123"})
    assert r_short.status_code == 400
    assert "at least 6 characters" in r_short.json()["detail"]

    # Successful login
    r_login = audit_client.post("/auth/login", json={"username": "alice_admin", "password": "Password123!"})
    assert r_login.status_code == 200
    assert "access_token" in r_login.json()

    # Wrong password
    r_wrong = audit_client.post("/auth/login", json={"username": "alice_admin", "password": "WrongPassword!"})
    assert r_wrong.status_code == 401

    # /auth/me with valid token
    r_me = audit_client.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert r_me.status_code == 200
    assert r_me.json()["username"] == "alice_admin"
    assert r_me.json()["role"] == "admin"

    # /auth/me with tampered token
    tampered = admin_token[:-5] + "XXXXX"
    r_tamp = audit_client.get("/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert r_tamp.status_code == 401

    # /auth/me with expired token
    from backend.auth import create_access_token
    expired_tok = create_access_token({"sub": "alice_admin", "role": "admin"}, expires_delta=timedelta(seconds=-10))
    r_exp = audit_client.get("/auth/me", headers={"Authorization": f"Bearer {expired_tok}"})
    assert r_exp.status_code == 401


# ==============================================================================
# 2. DOCUMENTS TESTS
# ==============================================================================

def test_documents_full_matrix(audit_client, tmp_path):
    # Setup users
    admin_tok = audit_client.post("/auth/register", json={"username": "doc_admin", "password": "Password123!"}).json()["access_token"]
    user_tok = audit_client.post("/auth/register", json={"username": "doc_user", "password": "Password123!"}).json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}
    user_hdr = {"Authorization": f"Bearer {user_tok}"}

    dummy_vector = [0.01] * EMBEDDING_DIM

    # 1. Upload TXT
    txt_content = b"Sovereign Workbench Architecture Document. Fully offline execution."
    with patch("backend.rag.ollama_client.embed", return_value=dummy_vector):
        r_txt = audit_client.post(
            "/documents/upload",
            headers=admin_hdr,
            files={"file": ("guide.txt", txt_content, "text/plain")},
        )
        assert r_txt.status_code == 200
        txt_doc_id = r_txt.json()["document_id"]

    # 2. Upload DOCX
    doc = docx.Document()
    doc.add_paragraph("Chapter 1: Agentic Workflows and Policy Gates in Sovereign AI.")
    buf_docx = io.BytesIO()
    doc.save(buf_docx)
    docx_bytes = buf_docx.getvalue()

    with patch("backend.rag.ollama_client.embed", return_value=dummy_vector):
        r_docx = audit_client.post(
            "/documents/upload",
            headers=user_hdr,
            files={"file": ("policy.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert r_docx.status_code == 200
        docx_doc_id = r_docx.json()["document_id"]

    # 3. Upload PDF with text
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buf_pdf = io.BytesIO()
    writer.write(buf_pdf)
    pdf_bytes = buf_pdf.getvalue()

    # Create PDF with readable text via mock
    with patch("backend.rag.DocumentParser.extract_text", return_value="Sample PDF readable content text"):
        with patch("backend.rag.ollama_client.embed", return_value=dummy_vector):
            r_pdf = audit_client.post(
                "/documents/upload",
                headers=admin_hdr,
                files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
            )
            assert r_pdf.status_code == 200

    # 4. List documents
    r_list = audit_client.get("/documents", headers=user_hdr)
    assert r_list.status_code == 200
    docs = r_list.json()
    assert len(docs) == 3

    # 5. Duplicate filename
    r_dup = audit_client.post(
        "/documents/upload",
        headers=admin_hdr,
        files={"file": ("guide.txt", b"New text", "text/plain")},
    )
    assert r_dup.status_code == 400
    assert "already exists" in r_dup.json()["detail"]

    # 6. Empty file (0 bytes)
    r_empty = audit_client.post(
        "/documents/upload",
        headers=admin_hdr,
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert r_empty.status_code == 400
    assert "empty" in r_empty.json()["detail"]

    # 7. File over 10 MB
    large_bytes = b"X" * (10 * 1024 * 1024 + 100)
    r_large = audit_client.post(
        "/documents/upload",
        headers=admin_hdr,
        files={"file": ("large.txt", large_bytes, "text/plain")},
    )
    assert r_large.status_code == 400
    assert "exceeds maximum allowed size" in r_large.json()["detail"]

    # 8. Unsupported file type (.exe)
    r_unsupp = audit_client.post(
        "/documents/upload",
        headers=admin_hdr,
        files={"file": ("malware.exe", b"MZ...", "application/octet-stream")},
    )
    assert r_unsupp.status_code == 400
    assert "Unsupported file extension" in r_unsupp.json()["detail"]

    # 9. Corrupt PDF
    r_corrupt = audit_client.post(
        "/documents/upload",
        headers=admin_hdr,
        files={"file": ("corrupt.pdf", b"Not a real PDF structure", "application/pdf")},
    )
    assert r_corrupt.status_code == 400

    # 10. Scanned PDF with no readable text
    r_notext = audit_client.post(
        "/documents/upload",
        headers=admin_hdr,
        files={"file": ("scanned.pdf", pdf_bytes, "application/pdf")},
    )
    assert r_notext.status_code == 400
    assert "no readable text" in r_notext.json()["detail"]

    # 11. Delete document authorization: user cannot delete admin's document
    r_del_denied = audit_client.delete(f"/documents/{txt_doc_id}", headers=user_hdr)
    assert r_del_denied.status_code == 403

    # User can delete their own document
    r_del_ok = audit_client.delete(f"/documents/{docx_doc_id}", headers=user_hdr)
    assert r_del_ok.status_code == 200

    # Admin can delete any document
    r_admin_del = audit_client.delete(f"/documents/{txt_doc_id}", headers=admin_hdr)
    assert r_admin_del.status_code == 200


# ==============================================================================
# 3. TOOLS TESTS
# ==============================================================================

def test_tools_matrix():
    # Calculator
    assert calculator("(10 + 5) * 4 / 2") == "30.0"
    assert "zero" in calculator("10 / 0").lower()
    assert "too large" in calculator("9999 ** 9999").lower()
    assert "error" in calculator("__import__('os').system('dir')").lower()
    assert "error" in calculator("eval('1+1')").lower()

    # Read File
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    test_f = upload_dir / "safe_test.txt"
    test_f.write_text("Secret content inside uploads.", encoding="utf-8")

    assert "Secret content" in read_file("safe_test.txt")
    assert "Security Error" in read_file("../backend/config.py")
    assert "Security Error" in read_file("../../.env")
    assert "Security Error" in read_file("C:/Windows/System32/drivers/etc/hosts")
    assert "Security Error" in read_file("C:\\Windows\\System32\\calc.exe")
    assert "not found" in read_file("nonexistent_file_xyz.txt")

    # Read SQL
    valid_res = read_sql("SELECT name, gpa FROM students WHERE gpa >= 3.8")
    assert "Aarav Sharma" in valid_res or "name" in valid_res
    assert "Security Error" in read_sql("DROP TABLE students")
    assert "Security Error" in read_sql("UPDATE students SET gpa = 4.0")
    assert "Security Error" in read_sql("SELECT * FROM students; DROP TABLE students")
    assert "Security Error" in read_sql("SELECT * FROM students -- comment")
    assert "Security Error" in read_sql("SELECT /* comment */ * FROM students")
    assert "Security Error" in read_sql("SELECT * FROM sqlite_master")
    assert "SQL Error" in read_sql("SELECT * FROM missing_table_12345")


# ==============================================================================
# 4. AGENT LOOP & POLICY TESTS
# ==============================================================================

def test_agent_loop_and_policy(audit_client):
    admin_tok = audit_client.post("/auth/register", json={"username": "agent_admin", "password": "Password123!"}).json()["access_token"]
    user_tok = audit_client.post("/auth/register", json={"username": "agent_user", "password": "Password123!"}).json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}
    user_hdr = {"Authorization": f"Bearer {user_tok}"}

    agents = audit_client.get("/agents", headers=user_hdr).json()
    analyst_agent = next(a for a in agents if a["name"] == "Data Analyst")

    # 1. High risk tool triggers approval pause
    sql_call = json.dumps({"action": "tool", "tool": "read_sql", "args": {"query": "SELECT * FROM students"}})
    with patch("backend.agent.ollama_client.chat", return_value=sql_call):
        res = audit_client.post(f"/agents/{analyst_agent['id']}/run", headers=user_hdr, json={"question": "Show students"})
        assert res.status_code == 200
        run_data = res.json()
        assert run_data["status"] == "paused_for_approval"
        apprv_id = run_data["approval_id"]
        run_id = run_data["run_id"]

    # 2. Check pending approvals
    pending_user = audit_client.get("/approvals/pending", headers=user_hdr).json()
    assert any(a["id"] == apprv_id for a in pending_user)

    # 3. Another normal user cannot decide someone else's approval
    other_user_tok = audit_client.post("/auth/register", json={"username": "other_user", "password": "Password123!"}).json()["access_token"]
    res_unauth = audit_client.post(
        f"/approvals/{apprv_id}/decide",
        headers={"Authorization": f"Bearer {other_user_tok}"},
        json={"decision": "approve"},
    )
    assert res_unauth.status_code == 403

    # 4. Deciding approval with approval decision -> Resumes run
    final_sql_ans = json.dumps({"action": "final", "answer": "Here are the students from database."})
    with patch("backend.agent.ollama_client.chat", return_value=final_sql_ans):
        res_decide = audit_client.post(
            f"/approvals/{apprv_id}/decide",
            headers=user_hdr,
            json={"decision": "approve"},
        )
        assert res_decide.status_code == 200
        res_data = res_decide.json()
        assert res_data["status"] == "resumed"
        assert res_data["decision"] == "approved"

    # 5. Double-deciding returns 400
    res_double = audit_client.post(
        f"/approvals/{apprv_id}/decide",
        headers=user_hdr,
        json={"decision": "approve"},
    )
    assert res_double.status_code == 400
    assert "already been decided" in res_double.json()["detail"]

    # 6. Approvals for nonexistent ID
    res_nonexist = audit_client.post(
        "/approvals/99999/decide",
        headers=user_hdr,
        json={"decision": "approve"},
    )
    assert res_nonexist.status_code == 404

    # 7. Trace and Run Object-Level Authorization
    trace_own = audit_client.get(f"/runs/{run_id}", headers=user_hdr)
    assert trace_own.status_code == 200
    steps = trace_own.json()["steps"]
    assert len(steps) > 0
    assert all("latency_ms" in s for s in steps)

    trace_forbidden = audit_client.get(f"/runs/{run_id}", headers={"Authorization": f"Bearer {other_user_tok}"})
    assert trace_forbidden.status_code == 403

    trace_admin = audit_client.get(f"/runs/{run_id}", headers=admin_hdr)
    assert trace_admin.status_code == 200


# ==============================================================================
# 5. ADMIN, AUDIT & HEALTH TESTS
# ==============================================================================

def test_admin_audit_and_health(audit_client):
    admin_tok = audit_client.post("/auth/register", json={"username": "super_adm", "password": "Password123!"}).json()["access_token"]
    user_tok = audit_client.post("/auth/register", json={"username": "norm_usr", "password": "Password123!"}).json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}
    user_hdr = {"Authorization": f"Bearer {user_tok}"}

    # 1. Manage users (GET /users)
    users_res = audit_client.get("/users", headers=admin_hdr)
    assert users_res.status_code == 200
    assert len(users_res.json()) >= 2

    user_denied = audit_client.get("/users", headers=user_hdr)
    assert user_denied.status_code == 403

    # 2. Create Agent
    create_res = audit_client.post(
        "/agents",
        headers=admin_hdr,
        json={
            "name": "Custom Math Agent",
            "system_prompt": "You are a math helper.",
            "allowed_tools": ["calculator"],
            "temperature": 0.3,
        },
    )
    assert create_res.status_code == 200
    new_agent_id = create_res.json()["id"]

    # Bad input: Unknown tool
    bad_tool = audit_client.post(
        "/agents",
        headers=admin_hdr,
        json={"name": "Bad Agent", "system_prompt": "...", "allowed_tools": ["nonexistent_tool"]},
    )
    assert bad_tool.status_code == 400

    # Bad input: Temperature out of range
    bad_temp = audit_client.post(
        "/agents",
        headers=admin_hdr,
        json={"name": "Hot Agent", "system_prompt": "...", "allowed_tools": ["calculator"], "temperature": 1.5},
    )
    assert bad_temp.status_code == 400

    # 3. Update Agent (PUT /agents/{id})
    update_res = audit_client.put(
        f"/agents/{new_agent_id}",
        headers=admin_hdr,
        json={
            "name": "Updated Math Agent",
            "system_prompt": "Updated prompt.",
            "allowed_tools": ["calculator"],
            "temperature": 0.5,
        },
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "Updated Math Agent"

    # User cannot update agent
    user_up_denied = audit_client.put(
        f"/agents/{new_agent_id}",
        headers=user_hdr,
        json={"name": "Hacked", "system_prompt": "...", "allowed_tools": ["calculator"]},
    )
    assert user_up_denied.status_code == 403

    # 4. Audit Log with filters
    user_audit_denied = audit_client.get("/audit", headers=user_hdr)
    assert user_audit_denied.status_code == 403

    admin_audit = audit_client.get("/audit?user=super_adm", headers=admin_hdr)
    assert admin_audit.status_code == 200
    logs = admin_audit.json()
    assert len(logs) > 0
    assert all(l["user"] == "super_adm" for l in logs)

    # 5. Health endpoint
    with patch("backend.llm.ollama_client.check_health", return_value={"reachable": True, "chat_model_present": True, "embed_model_present": True}):
        h_ok = audit_client.get("/health")
        assert h_ok.status_code == 200
        assert h_ok.json()["status"] == "healthy"

    with patch("backend.llm.ollama_client.check_health", return_value={"reachable": False, "chat_model_present": False, "embed_model_present": False}):
        h_down = audit_client.get("/health")
        assert h_down.status_code == 200
        assert h_down.json()["status"] == "degraded"


# ==============================================================================
# 6. ADVANCED AGENT LOOP EDGE CASES
# ==============================================================================

def test_agent_loop_advanced_matrix(audit_client, monkeypatch):
    admin_tok = audit_client.post("/auth/register", json={"username": "loop_adm", "password": "Password123!"}).json()["access_token"]
    admin_hdr = {"Authorization": f"Bearer {admin_tok}"}
    agents = audit_client.get("/agents", headers=admin_hdr).json()
    doc_agent = next(a for a in agents if a["name"] == "Document Assistant")

    # A: Malformed JSON that triggers a retry and succeeds on retry
    bad_json = "I cannot give you JSON right now, sorry."
    valid_final_json = json.dumps({"action": "final", "answer": "Recovered successfully after retry."})

    with patch("backend.agent.ollama_client.chat", side_effect=[bad_json, valid_final_json]):
        run_res = audit_client.post(
            f"/agents/{doc_agent['id']}/run",
            headers=admin_hdr,
            json={"question": "Trigger a retry test"},
        )
        assert run_res.status_code == 200
        run_data = run_res.json()
        assert run_data["status"] == "completed"
        assert "Recovered successfully" in run_data["answer"]

        # Verify trace contains retry step
        trace = audit_client.get(f"/runs/{run_data['run_id']}", headers=admin_hdr).json()
        step_types = [s["step_type"] for s in trace["steps"]]
        assert "retry" in step_types

    # B: ENABLE_RETRY=false immediately fails on malformed JSON
    monkeypatch.setattr(settings, "ENABLE_RETRY", False)
    with patch("backend.agent.ollama_client.chat", return_value=bad_json):
        run_no_retry = audit_client.post(
            f"/agents/{doc_agent['id']}/run",
            headers=admin_hdr,
            json={"question": "Fail without retry"},
        )
        assert run_no_retry.status_code == 200
        res_no_retry = run_no_retry.json()
        assert res_no_retry["status"] == "failed"
        assert "Model output format failure" in res_no_retry["answer"]

        # Verify no retry step exists
        trace_no_retry = audit_client.get(f"/runs/{res_no_retry['run_id']}", headers=admin_hdr).json()
        step_types_no_retry = [s["step_type"] for s in trace_no_retry["steps"]]
        assert "retry" not in step_types_no_retry
    monkeypatch.setattr(settings, "ENABLE_RETRY", True)

    # C: Unknown / non-allowlisted tool name
    # Model attempts to use 'delete_database' which is not allowlisted
    unauthorized_tool_call = json.dumps({
        "action": "tool",
        "tool": "delete_database",
        "args": {"force": True},
    })
    recovery_final = json.dumps({
        "action": "final",
        "answer": "I adapted after realizing delete_database was not permitted.",
    })
    with patch("backend.agent.ollama_client.chat", side_effect=[unauthorized_tool_call, recovery_final]):
        run_unauth = audit_client.post(
            f"/agents/{doc_agent['id']}/run",
            headers=admin_hdr,
            json={"question": "Try calling unauthorized tool"},
        )
        assert run_unauth.status_code == 200
        res_unauth = run_unauth.json()
        assert res_unauth["status"] == "completed"

        # Verify policy step recorded denial
        trace_unauth = audit_client.get(f"/runs/{res_unauth['run_id']}", headers=admin_hdr).json()
        policy_steps = [s for s in trace_unauth["steps"] if s["step_type"] == "policy"]
        assert any("denied" in s["output_data"].lower() for s in policy_steps)
