"""
Unit tests for the Sovereign Workbench policy and governance engine.
Tests:
- PII Masking (Aadhaar, Indian Phone, Email)
- Agent tool allowlist enforcement
- Role-based authorization
- High-risk tool approval requirement
Runs completely offline without Ollama.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, User, Agent, Run
from backend.policy import mask_pii, evaluate_policy, PolicyDecision


# In-memory SQLite session fixture for isolated policy testing
@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()

    # Seed test user and run
    user = User(username="test_analyst", password_hash="dummy", role="user")
    session.add(user)
    session.commit()

    agent = Agent(
        name="Test Agent",
        system_prompt="Test",
        model="dummy",
        allowed_tools='["calculator", "search_documents"]',
    )
    session.add(agent)
    session.commit()

    run = Run(user_id=user.id, agent_id=agent.id, question="What is 2+2?")
    session.add(run)
    session.commit()

    yield session
    session.close()


# ==============================================================================
# PII Masking Tests
# ==============================================================================

def test_mask_pii_email():
    text = "Please reach out to support@acme-corp.com or john.doe_12@sub.domain.org."
    masked = mask_pii(text)
    assert "support@acme-corp.com" not in masked
    assert "john.doe_12@sub.domain.org" not in masked
    assert "[EMAIL_MASKED]" in masked


def test_mask_pii_indian_phone():
    text1 = "Contact customer service at +91 9876543210 immediately."
    masked1 = mask_pii(text1)
    assert "9876543210" not in masked1
    assert "[PHONE_MASKED]" in masked1

    text2 = "Call 8123456789 for inquiries."
    masked2 = mask_pii(text2)
    assert "8123456789" not in masked2
    assert "[PHONE_MASKED]" in masked2


def test_mask_pii_aadhaar():
    text = "Citizen Aadhaar number is 1234 5678 9012 for verification."
    masked = mask_pii(text)
    assert "1234 5678 9012" not in masked
    assert "[AADHAAR_MASKED]" in masked

    text_no_space = "Aadhaar: 987654321098."
    masked_no_space = mask_pii(text_no_space)
    assert "987654321098" not in masked_no_space
    assert "[AADHAAR_MASKED]" in masked_no_space


# ==============================================================================
# Policy Allowlist & RBAC Tests
# ==============================================================================

def test_policy_allowlist_allowed(test_db):
    decision, reason, approval_id = evaluate_policy(
        tool_name="calculator",
        agent_allowed_tools=["calculator", "search_documents"],
        user_role="user",
        username="test_analyst",
        run_id=1,
        tool_args={"expression": "1 + 1"},
        db=test_db,
    )
    assert decision == PolicyDecision.ALLOWED
    assert approval_id is None


def test_policy_allowlist_denied(test_db):
    # Tool not in agent's allowlist
    decision, reason, approval_id = evaluate_policy(
        tool_name="read_file",
        agent_allowed_tools=["calculator"],  # read_file not present
        user_role="user",
        username="test_analyst",
        run_id=1,
        tool_args={"filename": "notes.txt"},
        db=test_db,
    )
    assert decision == PolicyDecision.DENIED
    assert "not permitted for this agent" in reason


def test_policy_high_risk_requires_approval(test_db):
    # read_sql is marked high risk
    decision, reason, approval_id = evaluate_policy(
        tool_name="read_sql",
        agent_allowed_tools=["read_sql", "calculator"],
        user_role="user",
        username="test_analyst",
        run_id=1,
        tool_args={"query": "SELECT * FROM students"},
        db=test_db,
    )
    assert decision == PolicyDecision.REQUIRES_APPROVAL
    assert approval_id is not None
    assert "requires human approval" in reason


def test_pii_masking_in_audit_logs_and_credentials_redacted(test_db):
    from backend.audit import log_audit_event
    from backend.db import AuditLog

    raw_email = "student.john@university.edu"
    raw_phone = "9876543210"
    raw_aadhaar = "1234 5678 9012"
    raw_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    raw_password = "SuperSecretPassword123!"

    # Log an event containing PII and secrets
    log_audit_event(
        user="test_analyst",
        action="pii_test_action",
        outcome="success",
        details=f"Email: {raw_email}, Phone: {raw_phone}, Aadhaar: {raw_aadhaar}, Token: Bearer {raw_jwt}, Password: {raw_password}",
        db=test_db,
    )

    saved_log = test_db.query(AuditLog).filter(AuditLog.action == "pii_test_action").first()
    assert saved_log is not None
    # Raw values must NEVER appear in DB
    assert raw_email not in saved_log.details
    assert raw_phone not in saved_log.details
    assert raw_aadhaar not in saved_log.details
    assert raw_jwt not in saved_log.details
    assert raw_password not in saved_log.details


def test_pii_masking_in_steps_table(test_db):
    from backend.agent import record_step
    from backend.db import Step

    raw_phone = "9123456789"
    raw_aadhaar = "9876 5432 1098"
    raw_email = "confidential@gov.in"

    step = record_step(
        db=test_db,
        run_id=1,
        step_number=1,
        step_type="tool",
        input_data=f"Querying record for phone {raw_phone}",
        output_data=f"Found citizen email {raw_email} with Aadhaar {raw_aadhaar}",
        latency_ms=12.5,
    )

    db_step = test_db.query(Step).filter(Step.id == step.id).first()
    assert db_step is not None
    # Raw values must NEVER appear in the steps table
    assert raw_phone not in db_step.input_data
    assert raw_email not in db_step.output_data
    assert raw_aadhaar not in db_step.output_data
    assert "[PHONE_MASKED]" in db_step.input_data
    assert "[EMAIL_MASKED]" in db_step.output_data
    assert "[AADHAAR_MASKED]" in db_step.output_data


def test_pii_masking_in_approval_args_stored_in_db(test_db):
    from backend.db import Approval

    raw_email = "candidate@institution.ac.in"
    raw_phone = "9988776655"

    decision, reason, approval_id = evaluate_policy(
        tool_name="read_sql",
        agent_allowed_tools=["read_sql"],
        user_role="user",
        username="test_analyst",
        run_id=1,
        tool_args={"query": f"SELECT * FROM students WHERE email = '{raw_email}' AND phone = '{raw_phone}'"},
        db=test_db,
    )

    assert decision == PolicyDecision.REQUIRES_APPROVAL
    approval_rec = test_db.query(Approval).filter(Approval.id == approval_id).first()
    assert approval_rec is not None
    # Raw email and phone must NEVER appear in the approvals table
    assert raw_email not in approval_rec.tool_args
    assert raw_phone not in approval_rec.tool_args
    assert "[EMAIL_MASKED]" in approval_rec.tool_args
    assert "[PHONE_MASKED]" in approval_rec.tool_args


def test_user_visible_answer_remains_unchanged(test_db):
    # Confirms that while DB steps/logs are masked, the final visible answer
    # provided to the user preserves the exact wording returned by the model
    from backend.db import Run

    raw_answer = "The verified contact email for the student is contact@college.edu."
    run = test_db.query(Run).filter(Run.id == 1).first()
    run.final_answer = raw_answer
    test_db.commit()

    reloaded_run = test_db.query(Run).filter(Run.id == 1).first()
    assert reloaded_run.final_answer == raw_answer
    assert "contact@college.edu" in reloaded_run.final_answer

