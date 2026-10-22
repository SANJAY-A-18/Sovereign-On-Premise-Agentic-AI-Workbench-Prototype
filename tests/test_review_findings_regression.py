"""
Regression tests for review findings (Finding H-1, H-2, M-1, M-3).
Post-eval verification on 'fixes' branch.
"""

import io
import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import settings
from backend.main import app, seed_default_agents
from backend.db import Base, get_db, User, Document, Run, reset_db_engine
from backend.auth import create_access_token, hash_password

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    Base.metadata.create_all(bind=test_engine)
    app.dependency_overrides[get_db] = override_get_db
    settings.UPLOAD_DIR = str(tmp_path / "uploads")
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

    db = TestingSession()
    seed_default_agents(db)
    db.close()
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def auth_client():
    """Provide a TestClient with an admin user."""
    db = TestingSession()
    admin = User(
        username="admin_tester",
        password_hash=hash_password("admin_pass123"),
        role="admin",
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    token = create_access_token({"sub": admin.username, "role": admin.role})
    db.close()

    client = TestClient(app)
    client.headers = {"Authorization": f"Bearer {token}"}
    return client


def test_h1_upload_document_chroma_failure_rollback(auth_client):
    """H-1: Ensure vector embedding failure cleans up DB record and unlinks file on disk."""
    client = auth_client
    file_bytes = b"Sample text for document failure rollback test."
    file_name = "test_rollback.txt"

    with patch("backend.rag.vector_store.add_document", side_effect=RuntimeError("Simulated Chroma OOM")):
        res = client.post(
            "/documents/upload",
            files={"file": (file_name, io.BytesIO(file_bytes), "text/plain")},
        )
        assert res.status_code == 500
        assert "vector embedding failed" in res.json()["detail"]

    # Verify no leaked file on disk
    dest_file = Path(settings.UPLOAD_DIR) / file_name
    assert not dest_file.exists(), "Disk file was not unlinked on embedding failure"

    # Verify no leaked DB record
    db = TestingSession()
    doc_in_db = db.query(Document).filter(Document.filename == file_name).first()
    db.close()
    assert doc_in_db is None, "Document record was not deleted from DB on embedding failure"

    # Verify user can now successfully upload the same filename once error is resolved
    with patch("backend.rag.vector_store.add_document", return_value=1):
        res2 = client.post(
            "/documents/upload",
            files={"file": (file_name, io.BytesIO(file_bytes), "text/plain")},
        )
        assert res2.status_code == 200
        assert res2.json()["filename"] == file_name


def test_m3_upload_document_filename_sanitization(auth_client):
    """M-3: Ensure hidden filenames and invalid traversals are rejected."""
    client = auth_client

    # Hidden file like .env or .bashrc
    res_hidden = client.post(
        "/documents/upload",
        files={"file": (".env", io.BytesIO(b"SECRET=123"), "text/plain")},
    )
    assert res_hidden.status_code == 400
    assert "Invalid or hidden filename" in res_hidden.json()["detail"] or "Unsupported" in res_hidden.json()["detail"]

    # URL encoded traversal
    with patch("backend.main.vector_store.add_document", return_value=1):
        res_traversal = client.post(
            "/documents/upload",
            files={"file": ("%2e%2e%2ftest_traversal.txt", io.BytesIO(b"content"), "text/plain")},
        )
        # Either successfully stripped to safe basename or rejected
        if res_traversal.status_code == 200:
            assert res_traversal.json()["filename"] == "test_traversal.txt"
        else:
            assert res_traversal.status_code == 400


def test_m1_reset_db_engine_reattaches_wal(tmp_path):
    """M-1: Ensure reset_db_engine re-attaches sqlite pragma listener for WAL & busy timeout."""
    test_db = tmp_path / "test_wal_verify.db"
    settings.DATABASE_URL = f"sqlite:///{test_db.as_posix()}"
    reset_db_engine()

    from backend.db import engine
    with engine.connect() as conn:
        journal_mode = conn.exec_driver_sql("PRAGMA journal_mode;").scalar()
        busy_timeout = conn.exec_driver_sql("PRAGMA busy_timeout;").scalar()

        assert str(journal_mode).upper() == "WAL"
        assert int(busy_timeout) >= 30000


def test_h2_run_agent_unhandled_exception_status_failed(auth_client):
    """H-2: Ensure unexpected runtime exceptions mark Run status as 'failed' in DB."""
    client = auth_client
    db = TestingSession()
    from backend.db import Agent
    agent = db.query(Agent).first()
    assert agent is not None

    with patch("backend.agent.AgentRunner.run_agent", side_effect=Exception("Database lock unexpected")):
        res = client.post(
            f"/agents/{agent.id}/run",
            json={"question": "What is the policy?"},
        )
        assert res.status_code == 500
        assert "unhandled error" in res.json()["detail"]

    # Verify run record in DB is marked 'failed'
    failed_run = db.query(Run).filter(Run.question == "What is the policy?").order_by(Run.id.desc()).first()
    assert failed_run is not None
    assert failed_run.status == "failed"
    assert "unhandled error" in failed_run.final_answer
    db.close()
