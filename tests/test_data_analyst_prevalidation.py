"""
Unit and integration tests for Data Analyst pre-approval validation and runtime schema injection.
Validates:
1. Static read_sql checks run BEFORE creating an approval request (Item 4).
2. Invalid queries (non-SELECT, compound statements, non-existent tables) are rejected without human approval.
3. Runtime demo SQLite schema (sqlite_master / PRAGMA table_info) is injected into agent context (Item 5).
4. Repeated identical tool calls after an error or denial are blocked (Item 4).
5. Full mocked LLM execution verifying error recovery and schema awareness.
"""

import json
from unittest.mock import patch, MagicMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.agent import AgentRunner, build_system_prompt
from backend.db import Base, User, Agent, Run, Step, Approval, init_demo_db
from backend.policy import evaluate_policy, PolicyDecision
from backend.tools import get_demo_db_schema, validate_sql_query, tool_registry


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    init_demo_db()  # Ensure demo.db has students table
    db = TestingSession()
    try:
        # Seed test admin and user
        admin = User(username="admin", password_hash="hash", role="admin")
        user = User(username="testuser", password_hash="hash", role="user")
        db.add_all([admin, user])
        db.commit()

        # Seed Data Analyst agent
        analyst = Agent(
            id=2,
            name="Data Analyst",
            system_prompt="You are a data analyst.",
            model="qwen2.5:3b",
            temperature=0.1,
            allowed_tools=json.dumps(["read_sql", "calculator"]),
        )
        db.add(analyst)
        db.commit()
        yield db
    finally:
        db.close()


def test_schema_extraction_at_runtime():
    schema = get_demo_db_schema()
    assert "students" in schema
    assert "gpa" in schema
    assert "marks" in schema
    assert "department" in schema


def test_system_prompt_includes_sqlite_schema(test_db):
    agent = test_db.query(Agent).filter(Agent.name == "Data Analyst").first()
    tools_info = [tool_registry.get(t).to_definition().model_dump() for t in json.loads(agent.allowed_tools)]
    prompt = build_system_prompt(agent, tools_info)
    assert "DEMO DATABASE SCHEMA (SQLite)" in prompt
    assert "Table 'students'" in prompt
    assert "Do NOT query MySQL information_schema" in prompt


def test_validate_sql_query_valid():
    is_valid, query_or_err = validate_sql_query("SELECT COUNT(*) FROM students WHERE gpa > 3.80")
    assert is_valid is True
    assert query_or_err == "SELECT COUNT(*) FROM students WHERE gpa > 3.80"


def test_validate_sql_query_rejects_show_tables():
    is_valid, query_or_err = validate_sql_query("SHOW TABLES")
    assert is_valid is False
    assert "Security Error" in query_or_err or "SQL Error" in query_or_err


def test_validate_sql_query_rejects_compound_statements():
    is_valid, query_or_err = validate_sql_query("SELECT * FROM students; DROP TABLE students")
    assert is_valid is False
    assert "Multiple SQL statements" in query_or_err


def test_validate_sql_query_rejects_non_existent_table():
    is_valid, query_or_err = validate_sql_query("SELECT * FROM information_schema.tables")
    assert is_valid is False
    assert "no such table" in query_or_err.lower() or "sql error" in query_or_err.lower()


def test_policy_rejects_invalid_sql_without_human_approval(test_db):
    user = test_db.query(User).filter(User.username == "testuser").first()
    run = Run(user_id=user.id, agent_id=2, question="List tables", status="running")
    test_db.add(run)
    test_db.commit()

    decision, reason, approval_id = evaluate_policy(
        tool_name="read_sql",
        agent_allowed_tools=["read_sql", "calculator"],
        user_role="user",
        username=user.username,
        run_id=run.id,
        tool_args={"query": "SHOW TABLES"},
        db=test_db,
    )

    # Must be DENIED without creating an approval
    assert decision == PolicyDecision.DENIED
    assert approval_id is None
    assert "Real database schema" in reason
    assert "Table 'students'" in reason

    # Verify zero approvals were created in DB
    approvals_count = test_db.query(Approval).filter(Approval.run_id == run.id).count()
    assert approvals_count == 0


def test_policy_creates_approval_only_for_valid_sql(test_db):
    user = test_db.query(User).filter(User.username == "testuser").first()
    run = Run(user_id=user.id, agent_id=2, question="Count top students", status="running")
    test_db.add(run)
    test_db.commit()

    decision, reason, approval_id = evaluate_policy(
        tool_name="read_sql",
        agent_allowed_tools=["read_sql", "calculator"],
        user_role="user",
        username=user.username,
        run_id=run.id,
        tool_args={"query": "SELECT COUNT(*) FROM students WHERE gpa > 3.80"},
        db=test_db,
    )

    # Valid query passes static checks and reaches high-risk approval
    assert decision == PolicyDecision.REQUIRES_APPROVAL
    assert approval_id is not None
    approval = test_db.query(Approval).filter(Approval.id == approval_id).first()
    assert approval is not None
    assert "SELECT COUNT(*)" in approval.tool_args


def test_block_duplicate_tool_call_after_error(test_db, monkeypatch):
    user = test_db.query(User).filter(User.username == "testuser").first()
    run = Run(user_id=user.id, agent_id=2, question="Test repeat query", status="pending")
    test_db.add(run)
    test_db.commit()

    # LLM attempts SHOW TABLES on turn 1, then attempts identical SHOW TABLES on turn 2, then finalizes
    responses = [
        json.dumps({"action": "tool", "tool": "read_sql", "args": {"query": "SHOW TABLES"}}),
        json.dumps({"action": "tool", "tool": "read_sql", "args": {"query": "SHOW TABLES"}}),
        json.dumps({"action": "final", "answer": "I could not list tables."}),
    ]
    call_idx = [0]

    def mock_chat(*args, **kwargs):
        resp = responses[min(call_idx[0], len(responses) - 1)]
        call_idx[0] += 1
        return resp

    from backend.llm import ollama_client
    monkeypatch.setattr(ollama_client, "chat", mock_chat)

    result = AgentRunner.run_agent(run.id, test_db)
    assert result["status"] == "completed"

    # Verify steps: step 2 was policy denial, step 3 blocked the duplicate call
    steps = test_db.query(Step).filter(Step.run_id == run.id).order_by(Step.step_number).all()
    step_types = [s.step_type for s in steps]
    assert "policy" in step_types

    # Find the blocked duplicate step
    blocked_steps = [s for s in steps if "Blocked duplicate" in s.input_data or "Repeated invocation blocked" in s.output_data]
    assert len(blocked_steps) > 0, "Duplicate tool call must be blocked"

    # Zero approvals should have been created throughout
    approvals_count = test_db.query(Approval).filter(Approval.run_id == run.id).count()
    assert approvals_count == 0
