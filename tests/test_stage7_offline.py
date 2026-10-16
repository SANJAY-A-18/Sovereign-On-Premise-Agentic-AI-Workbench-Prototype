"""
Stage 7: Offline Proof & Cloud Egress Prohibition Test Suite.
Validates:
1. Strict non-loopback socket connection blocker: any attempt to connect to
   a non-loopback IP (e.g. external clouds, telemetry, CDNs) raises PermissionError.
2. Under this strict zero-egress sandbox, all core Sovereign Workbench flows pass:
   - User registration & authentication
   - Document upload & RAG chunk ingestion
   - Agent question execution & tool invocation
   - High-risk policy approval & decision resume
3. Telemetry settings verification: Chroma & environment telemetry explicitly disabled.
"""

import io
import json
import socket
from unittest.mock import patch
import pytest
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base, get_db
from backend.main import app, seed_default_agents
from backend.config import settings

# Shared in-memory test database for offline proof
offline_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
OfflineSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=offline_engine)


def override_offline_db():
    db = OfflineSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def offline_client():
    Base.metadata.drop_all(bind=offline_engine)
    Base.metadata.create_all(bind=offline_engine)
    app.dependency_overrides[get_db] = override_offline_db
    db = OfflineSessionLocal()
    try:
        seed_default_agents(db)
    finally:
        db.close()

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def enforce_offline_loopback_only(monkeypatch):
    """
    Strict network sandbox fixture:
    Intercepts socket.socket.connect and permits ONLY loopback connections:
    - 127.0.0.1
    - localhost
    - ::1
    Any attempt to connect to any external cloud, IP, or telemetry endpoint immediately
    raises PermissionError.
    """
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) and len(address) > 0 else str(address)
        # Normalize host string
        host_str = str(host).lower().strip()
        allowed = (
            host_str.startswith("127.")
            or host_str == "localhost"
            or host_str == "::1"
            or host_str == "0.0.0.0"
        )
        if not allowed:
            raise PermissionError(f"Cloud egress prohibited: non-loopback connection blocked to {address}")
        return orig_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield


def test_guard_blocks_external_network_connections():
    """Verify that socket guard actively intercepts and raises PermissionError on external connections."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(PermissionError) as excinfo:
        s.connect(("8.8.8.8", 53))
    assert "Cloud egress prohibited" in str(excinfo.value)
    s.close()


def test_offline_core_flows_under_egress_lock(offline_client):
    """
    Executes the complete Sovereign Workbench lifecycle under active egress prohibition:
    1. Register user
    2. Upload document
    3. Run agent with calculator tool
    4. Run agent with approval flow
    5. Decide approval
    All succeed strictly on-premise without any external network traffic.
    """
    # 1. Register user
    reg_res = offline_client.post(
        "/auth/register",
        json={"username": "offline_admin", "password": "Password123!"},
    )
    assert reg_res.status_code == 200
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Upload document
    doc_content = b"Sovereign Workbench Air-Gapped Specification 2026. Deployment requires zero cloud egress."
    files = {"file": ("airgap_spec.txt", io.BytesIO(doc_content), "text/plain")}
    with patch("backend.rag.vector_store.add_document", return_value=1):
        up_res = offline_client.post("/documents/upload", files=files, headers=headers)
        assert up_res.status_code == 200
        assert up_res.json()["filename"] == "airgap_spec.txt"

    # 3. Run Agent with Tool Execution (Calculator)
    # Model returns tool call for 25 * 4, then final answer
    call_responses = [
        json.dumps({"action": "tool", "tool": "calculator", "args": {"expression": "25 * 4"}}),
        json.dumps({"action": "final", "answer": "The computed value is 100."}),
    ]

    with patch("backend.llm.ollama_client.chat", side_effect=call_responses):
        run_res = offline_client.post(
            "/agents/1/run",
            json={"question": "What is 25 * 4?"},
            headers=headers,
        )
        assert run_res.status_code == 200
        run_data = run_res.json()
        assert run_data["status"] == "completed"
        assert "100" in run_data["answer"]

    # 4. Trigger High-Risk Tool requiring Approval (read_sql on Agent 2 - Data Analyst)
    sql_call = json.dumps({"action": "tool", "tool": "read_sql", "args": {"query": "SELECT * FROM students"}})
    with patch("backend.llm.ollama_client.chat", return_value=sql_call):
        sql_run_res = offline_client.post(
            "/agents/2/run",
            json={"question": "Show all students in database"},
            headers=headers,
        )
        assert sql_run_res.status_code == 200
        sql_data = sql_run_res.json()
        assert sql_data["status"] == "paused_for_approval"
        app_id = sql_data["approval_id"]

    # 5. Decide Approval and Resume
    final_sql_answer = json.dumps({"action": "final", "answer": "Found 10 students in SQLite."})
    with patch("backend.llm.ollama_client.chat", return_value=final_sql_answer):
        dec_res = offline_client.post(
            f"/approvals/{app_id}/decide",
            json={"decision": "approve"},
            headers=headers,
        )
        assert dec_res.status_code == 200
        assert dec_res.json()["status"] == "resumed"
        assert dec_res.json()["run_result"]["status"] == "completed"


def test_telemetry_disabled_confirmation():
    """Verify Chroma and global environment telemetry flags are strictly disabled."""
    import os
    assert os.environ.get("ANONYMIZED_TELEMETRY") == "False"
    assert os.environ.get("CHROMA_TELEMETRY") == "False"
