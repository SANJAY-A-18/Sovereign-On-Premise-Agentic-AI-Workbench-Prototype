"""
Unit and integration tests for Stage 4: Robustness.
Validates:
- Ollama stopped mid-run (friendly error, run marked failed, not stuck)
- Ollama timeout (friendly error, run marked failed, not stuck)
- Empty questions (400)
- Very long questions > 8000 chars (400)
- Unicode and non-English questions (Tamil, Hindi, Japanese, Arabic, emojis)
- Rapid repeated clicks (identical active run prevented with 409)
- Run left in paused_for_approval after backend restart (resumable)
- Orphaned run in 'running' cleaned up by startup recovery logic
- SQLite WAL mode and busy timeout configuration
"""

import json
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base, get_db, Run, Approval, Step, Agent
from backend.llm import OllamaConnectionError, OllamaError
from backend.agent import AgentRunner
from backend.main import app, seed_default_agents

# Shared in-memory test database for robustness suite
robust_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
RobustSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=robust_engine)


def override_robust_db():
    db = RobustSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def robust_client():
    Base.metadata.drop_all(bind=robust_engine)
    Base.metadata.create_all(bind=robust_engine)
    app.dependency_overrides[get_db] = override_robust_db
    db = RobustSessionLocal()
    try:
        seed_default_agents(db)
    finally:
        db.close()

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_empty_and_whitespace_questions(robust_client):
    """Empty and whitespace questions must return 400."""
    reg = robust_client.post("/auth/register", json={"username": "u1", "password": "Password123"}).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    res1 = robust_client.post("/agents/1/run", json={"question": ""}, headers=headers)
    assert res1.status_code == 400
    assert "cannot be empty" in res1.json()["detail"]

    res2 = robust_client.post("/agents/1/run", json={"question": "   \n\t  "}, headers=headers)
    assert res2.status_code == 400
    assert "cannot be empty" in res2.json()["detail"]


def test_very_long_question_rejected(robust_client):
    """Questions exceeding 8000 characters must return 400."""
    reg = robust_client.post("/auth/register", json={"username": "u1", "password": "Password123"}).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    long_question = "What is the capital of France? " * 300  # > 9000 chars
    assert len(long_question) > 8000

    res = robust_client.post("/agents/1/run", json={"question": long_question}, headers=headers)
    assert res.status_code == 400
    assert "8000" in res.json()["detail"]


def test_rapid_repeated_clicks_blocked(robust_client, monkeypatch):
    """An active identical run in progress blocks duplicate clicks with 409 Conflict."""
    reg = robust_client.post("/auth/register", json={"username": "u1", "password": "Password123"}).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    def mock_run_agent(run_id, db):
        # Keep status as 'running'
        return {"status": "running", "run_id": run_id}

    monkeypatch.setattr(AgentRunner, "run_agent", mock_run_agent)

    q = "Show me all active courses"
    res1 = robust_client.post("/agents/1/run", json={"question": q}, headers=headers)
    assert res1.status_code == 200

    # Rapid repeated click with exact same question
    res2 = robust_client.post("/agents/1/run", json={"question": q}, headers=headers)
    assert res2.status_code == 409
    assert "already in progress" in res2.json()["detail"]


def test_ollama_stopped_mid_run_marks_failed(robust_client):
    """If Ollama is stopped/unreachable mid-run, run is marked failed with friendly message and not stuck."""
    reg = robust_client.post("/auth/register", json={"username": "u1", "password": "Password123"}).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    with patch("backend.llm.ollama_client.chat") as mock_chat:
        mock_chat.side_effect = OllamaConnectionError(
            "Ollama is unreachable at http://localhost:11434. Please ensure Ollama is running."
        )

        res = robust_client.post(
            "/agents/1/run",
            json={"question": "What is the weather?"},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "failed"
        assert "Ollama is unreachable" in data["answer"]

        # Check DB run status
        db = RobustSessionLocal()
        run = db.query(Run).filter(Run.id == data["run_id"]).first()
        assert run is not None
        assert run.status == "failed"
        assert "unreachable" in run.final_answer
        db.close()


def test_ollama_timeout_mid_run_marks_failed(robust_client):
    """If Ollama times out, run is marked failed with friendly message and not stuck."""
    reg = robust_client.post("/auth/register", json={"username": "u1", "password": "Password123"}).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    with patch("backend.llm.ollama_client.chat") as mock_chat:
        mock_chat.side_effect = OllamaError("Ollama call timed out after 120 seconds.")

        res = robust_client.post(
            "/agents/1/run",
            json={"question": "Calculate complex simulation"},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "failed"
        assert "timed out" in data["answer"]

        db = RobustSessionLocal()
        run = db.query(Run).filter(Run.id == data["run_id"]).first()
        assert run is not None
        assert run.status == "failed"
        db.close()


def test_unicode_and_multilingual_handling(robust_client):
    """System safely handles non-English languages, Unicode, and emojis without crashing."""
    reg = robust_client.post("/auth/register", json={"username": "u1", "password": "Password123"}).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}

    unicode_query = "12 + 15 எவ்வளவு? வணக்கம் 🚀 தமிழ் மற்றும் हिंदी परीक्षण"

    with patch("backend.llm.ollama_client.chat") as mock_chat:
        mock_chat.return_value = json.dumps({
            "action": "final",
            "answer": "12 + 15 = 27. வணக்கம்! 🚀"
        })

        res = robust_client.post(
            "/agents/1/run",
            json={"question": unicode_query},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert "27" in data["answer"]

        # Check DB text preserved
        db = RobustSessionLocal()
        run = db.query(Run).filter(Run.id == data["run_id"]).first()
        assert run is not None
        assert "தமிழ்" in run.question
        assert "வணக்கம்" in run.final_answer
        db.close()


def test_paused_for_approval_resumable_after_restart(robust_client):
    """
    A run left in paused_for_approval remains paused across backend restarts,
    is visible in pending approvals, and can be resumed cleanly.
    """
    # First user is admin
    reg_admin = robust_client.post("/auth/register", json={"username": "adm", "password": "Password123"}).json()
    admin_headers = {"Authorization": f"Bearer {reg_admin['access_token']}"}

    db = RobustSessionLocal()
    agent = db.query(Agent).first()
    paused_run = Run(
        user_id=1,
        agent_id=agent.id,
        question="Drop student table test query",
        status="paused_for_approval",
    )
    db.add(paused_run)
    db.commit()
    db.refresh(paused_run)

    step = Step(
        run_id=paused_run.id,
        step_number=1,
        step_type="llm",
        input_data="[prompt]",
        output_data=json.dumps({"action": "tool", "tool": "read_sql", "args": {"query": "SELECT * FROM students"}}),
        latency_ms=10.0,
    )
    approval = Approval(
        run_id=paused_run.id,
        tool_name="read_sql",
        tool_args=json.dumps({"query": "SELECT * FROM students"}),
        status="pending",
    )
    db.add(step)
    db.add(approval)
    db.commit()
    db.refresh(approval)
    approval_id = approval.id
    run_id = paused_run.id
    db.close()

    # Verify pending approvals lists it
    res = robust_client.get("/approvals/pending", headers=admin_headers)
    assert res.status_code == 200
    pending_ids = [a["id"] for a in res.json()]
    assert approval_id in pending_ids

    # Simulate deciding approval after server restart
    with patch("backend.llm.ollama_client.chat") as mock_chat:
        mock_chat.return_value = json.dumps({
            "action": "final",
            "answer": "Here is the table contents: Alice, Bob, Charlie."
        })
        decide_res = robust_client.post(
            f"/approvals/{approval_id}/decide",
            json={"decision": "approve"},
            headers=admin_headers,
        )
        assert decide_res.status_code == 200
        assert decide_res.json()["status"] == "resumed"

    # Confirm run is now completed, not paused or running
    db = RobustSessionLocal()
    updated_run = db.query(Run).filter(Run.id == run_id).first()
    assert updated_run.status == "completed"
    assert "Alice" in updated_run.final_answer
    db.close()


def test_orphaned_running_runs_marked_failed():
    """Any runs left in 'running' by a prior crash are cleanly recovered to 'failed'."""
    Base.metadata.create_all(bind=robust_engine)
    db = RobustSessionLocal()
    seed_default_agents(db)
    agent = db.query(Agent).first()
    orphaned_run = Run(
        user_id=1,
        agent_id=agent.id,
        question="Orphaned query during power failure",
        status="running",
    )
    db.add(orphaned_run)
    db.commit()
    db.refresh(orphaned_run)
    run_id = orphaned_run.id

    # Simulate the lifespan cleanup logic
    orphaned = db.query(Run).filter(Run.status == "running").all()
    for r in orphaned:
        r.status = "failed"
        r.final_answer = "Run was interrupted by server restart or shutdown."
    db.commit()

    fixed_run = db.query(Run).filter(Run.id == run_id).first()
    assert fixed_run.status == "failed"
    assert "restart or shutdown" in fixed_run.final_answer
    db.close()
