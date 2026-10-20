"""
Integration tests for FastAPI endpoints using TestClient.
Tests:
- First user registration becomes admin
- Second user registration becomes user
- Login returns JWT
- Health check returns Ollama status cleanly
- Document listing
- Agent listing & creation
Runs completely offline without Ollama running.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.db import Base, get_db

# Test in-memory SQLite with StaticPool so all threads/sessions share the database
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
    from backend.main import seed_default_agents
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


def test_liveness_check_endpoint(client):
    """Verify /live endpoint returns 200 and alive status without querying Ollama."""
    res = client.get("/live")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "alive"
    assert "timestamp" in data
    assert "system" in data


def test_health_check_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "ollama" in data
    assert "configured_chat_model" in data["ollama"]


def test_auth_first_user_admin_second_user_regular(client):
    # 1. First user registers -> role should be admin
    res1 = client.post(
        "/auth/register",
        json={"username": "admin_user", "password": "AdminPassword123!"},
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["role"] == "admin"
    assert "access_token" in data1

    # 2. Second user registers -> role should be user
    res2 = client.post(
        "/auth/register",
        json={"username": "regular_user", "password": "UserPassword123!"},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["role"] == "user"
    assert "access_token" in data2


def test_login_flow(client):
    # Register user
    client.post(
        "/auth/register",
        json={"username": "alice", "password": "SecretPassword123"},
    )

    # Valid Login
    login_res = client.post(
        "/auth/login",
        json={"username": "alice", "password": "SecretPassword123"},
    )
    assert login_res.status_code == 200
    data = login_res.json()
    assert "access_token" in data
    assert data["username"] == "alice"

    # Invalid Login
    bad_res = client.post(
        "/auth/login",
        json={"username": "alice", "password": "WrongPassword"},
    )
    assert bad_res.status_code == 401


def test_list_agents_endpoint(client):
    # Register and get token
    reg = client.post(
        "/auth/register",
        json={"username": "doc_owner", "password": "Password123"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Query agents
    res = client.get("/agents", headers=headers)
    assert res.status_code == 200
    agents = res.json()
    assert isinstance(agents, list)
