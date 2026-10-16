"""
End-to-End Acceptance Tests verifying requirements 3, 4, and 5 from MASTER_PROTOTYPE_PROMPT.md:
- First user registers as admin, logs in
- Document upload (.txt) and ingestion into knowledge base
- Document Assistant queries RAG and cites sources
- Data Analyst invokes high-risk read_sql, run pauses for approval
- Approval resumes the run and returns the result
- Denial path is verified
- Traces and Audit logs record all decisions and latencies
"""

import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app, seed_default_agents
from backend.db import Base, get_db
from backend.config import EMBEDDING_DIM

# Shared in-memory database for full acceptance verification
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()
    try:
        seed_default_agents(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_full_acceptance_workflow(client):
    # ==========================================================================
    # 1. Register first user -> must be admin
    # ==========================================================================
    reg_res = client.post(
        "/auth/register",
        json={"username": "superadmin", "password": "AdminPassword123!"},
    )
    assert reg_res.status_code == 200
    admin_auth = reg_res.json()
    assert admin_auth["role"] == "admin"
    token = admin_auth["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # ==========================================================================
    # 2. Upload a TXT document for RAG
    # ==========================================================================
    sample_text = (
        "Project Titan Revenue Report: Total revenue for Q3 2026 was 12.5 million dollars. "
        "The leading division was Autonomous Systems with 7.2 million dollars in earnings."
    )
    files = {"file": ("titan_report.txt", sample_text.encode("utf-8"), "text/plain")}

    # Mock Ollama embedding vector derived from central EMBEDDING_DIM constant
    dummy_vector = [0.05] * EMBEDDING_DIM
    with patch("backend.rag.ollama_client.embed", return_value=dummy_vector):
        upload_res = client.post("/documents/upload", headers=headers, files=files)
        assert upload_res.status_code == 200
        up_data = upload_res.json()
        assert up_data["status"] == "success"
        assert up_data["filename"] == "titan_report.txt"

    # Verify document listing
    doc_list = client.get("/documents", headers=headers).json()
    assert len(doc_list) == 1
    assert doc_list[0]["filename"] == "titan_report.txt"

    # ==========================================================================
    # 3. Document Assistant Run with Citations
    # ==========================================================================
    # Get Document Assistant agent
    agents = client.get("/agents", headers=headers).json()
    doc_agent = next(a for a in agents if a["name"] == "Document Assistant")

    # Mock LLM sequence:
    # Call 1: model decides to call search_documents
    # Call 2: model observes search results and gives final answer with citation
    tool_call_json = json.dumps({
        "action": "tool",
        "tool": "search_documents",
        "args": {"query": "Project Titan revenue"},
    })
    final_answer_json = json.dumps({
        "action": "final",
        "answer": "According to the Titan report [Source: titan_report.txt | Chunk #0], total revenue for Q3 2026 was 12.5 million dollars.",
    })

    with patch("backend.agent.ollama_client.chat", side_effect=[tool_call_json, final_answer_json]):
        with patch("backend.rag.ollama_client.embed", return_value=dummy_vector):
            run_res = client.post(
                f"/agents/{doc_agent['id']}/run",
                headers=headers,
                json={"question": "What was the Q3 revenue for Project Titan?"},
            )
            assert run_res.status_code == 200
            run_data = run_res.json()
            assert run_data["status"] == "completed"
            assert "12.5 million" in run_data["answer"]
            assert len(run_data.get("sources", [])) > 0
            doc_run_id = run_data["run_id"]

    # ==========================================================================
    # 4. Data Analyst Run with read_sql -> Approval Required -> Resumed
    # ==========================================================================
    analyst_agent = next(a for a in agents if a["name"] == "Data Analyst")

    sql_call_json = json.dumps({
        "action": "tool",
        "tool": "read_sql",
        "args": {"query": "SELECT name, gpa FROM students WHERE gpa > 3.8"},
    })
    sql_final_json = json.dumps({
        "action": "final",
        "answer": "The top students with GPA above 3.8 are Aarav Sharma (3.85), Ananya Sen (3.92), and Meera Nair (3.88).",
    })

    # Step A: Initiate Run -> Must pause for approval
    with patch("backend.agent.ollama_client.chat", return_value=sql_call_json):
        analyst_run_res = client.post(
            f"/agents/{analyst_agent['id']}/run",
            headers=headers,
            json={"question": "List students with GPA over 3.8"},
        )
        assert analyst_run_res.status_code == 200
        paused_data = analyst_run_res.json()
        assert paused_data["status"] == "paused_for_approval"
        approval_id = paused_data["approval_id"]
        analyst_run_id = paused_data["run_id"]

    # Step B: Check pending approvals endpoint
    pending_list = client.get("/approvals/pending", headers=headers).json()
    assert len(pending_list) == 1
    assert pending_list[0]["id"] == approval_id
    assert pending_list[0]["tool_name"] == "read_sql"

    # Step C: Approve the action -> Agent resumes and completes
    with patch("backend.agent.ollama_client.chat", return_value=sql_final_json):
        decide_res = client.post(
            f"/approvals/{approval_id}/decide",
            headers=headers,
            json={"decision": "approve"},
        )
        assert decide_res.status_code == 200
        resume_data = decide_res.json()
        assert resume_data["status"] == "resumed"
        assert resume_data["decision"] == "approved"
        assert resume_data["run_result"]["status"] == "completed"
        assert resume_data["run_result"]["run_id"] == analyst_run_id
        assert "Aarav Sharma" in resume_data["run_result"]["answer"]

    # Step D: Test Denial Path on a second run
    with patch("backend.agent.ollama_client.chat", return_value=sql_call_json):
        deny_run_res = client.post(
            f"/agents/{analyst_agent['id']}/run",
            headers=headers,
            json={"question": "Another query requiring SQL"},
        )
        deny_approval_id = deny_run_res.json()["approval_id"]

    denial_final_json = json.dumps({
        "action": "final",
        "answer": "The database query was not approved by the supervisor, so I cannot provide SQL records.",
    })
    with patch("backend.agent.ollama_client.chat", return_value=denial_final_json):
        deny_decide_res = client.post(
            f"/approvals/{deny_approval_id}/decide",
            headers=headers,
            json={"decision": "deny"},
        )
        assert deny_decide_res.status_code == 200
        assert deny_decide_res.json()["decision"] == "denied"
        assert "not approved" in deny_decide_res.json()["run_result"]["answer"]

    # ==========================================================================
    # 5. Verify Traces with Latencies and Audit Log with Policy Decisions
    # ==========================================================================
    # Check trace for the Document Assistant run
    trace_res = client.get(f"/runs/{doc_run_id}", headers=headers)
    assert trace_res.status_code == 200
    trace_data = trace_res.json()
    assert len(trace_data["steps"]) >= 2
    for step in trace_data["steps"]:
        assert "latency_ms" in step
        assert step["step_type"] in ("llm", "tool", "policy", "retry")

    # Check Audit Log endpoint (Admin only)
    audit_res = client.get("/audit", headers=headers)
    assert audit_res.status_code == 200
    audit_logs = audit_res.json()
    assert len(audit_logs) > 0
    actions = [a["action"] for a in audit_logs]
    assert any("user_registered" in a for a in actions)
    assert any("document_uploaded" in a for a in actions)
    assert any("policy_approval_request" in a for a in actions)
    assert any("approval_decision" in a for a in actions)
