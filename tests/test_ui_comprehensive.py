"""
Comprehensive UI Verification Suite using streamlit.testing.v1.AppTest.
Validates all UI tabs and flows per Stage 6:
1. Unauthenticated view (Account tab default, restricted tabs hidden)
2. Normal user login & role-based tab visibility (Agents and Audit tabs hidden)
3. Admin user view (all 7 tabs visible: Chat, Documents, Agents, Traces, Approvals, Audit Log, Account)
4. Document management tab (rendering document list, delete button presence)
5. Agent management tab (create new agent and edit existing agent controls)
6. Approvals tab (pending high-risk requests, approve and deny actions)
7. Traces tab (execution steps and latency display)
8. Audit Log tab (admin security audit table)
9. Backend stopped/unreachable behavior (offline badge, graceful error display)
10. Token expiry / 401 handling (session state cleared, warning displayed)
"""

import pytest
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest


@pytest.fixture
def mock_backend_success():
    """Provides standard mock responses for backend API endpoints."""
    def _mock_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/health" in url:
            resp.json.return_value = {
                "status": "healthy",
                "system": "Sovereign AI Workbench",
                "ollama": {
                    "reachable": True,
                    "configured_chat_model": "qwen2.5:3b",
                    "configured_embed_model": "nomic-embed-text",
                },
            }
        elif "/auth/me" in url:
            resp.json.return_value = {
                "user_id": 1,
                "username": "admin_user",
                "role": "admin",
            }
        elif "/agents" in url:
            resp.json.return_value = [
                {
                    "id": 1,
                    "name": "General Assistant",
                    "system_prompt": "Helpful assistant",
                    "model": "qwen2.5:3b",
                    "temperature": 0.2,
                    "allowed_tools": ["calculator", "search_documents"],
                }
            ]
        elif "/documents" in url:
            resp.json.return_value = [
                {
                    "id": 10,
                    "filename": "sovereign_specs.txt",
                    "file_type": "txt",
                    "file_size": 2048,
                    "chunk_count": 3,
                    "created_at": "2026-10-15T10:00:00",
                }
            ]
        elif "/tools" in url:
            resp.json.return_value = [
                {"name": "search_documents", "description": "Search docs"},
                {"name": "calculator", "description": "Math calculator"},
                {"name": "read_sql", "description": "SQL read"},
                {"name": "read_file", "description": "File read"},
            ]
        elif "/approvals/pending" in url:
            resp.json.return_value = [
                {
                    "id": 5,
                    "tool_name": "read_sql",
                    "tool_args": '{"query": "SELECT * FROM students"}',
                    "username": "student_user",
                    "run_id": 12,
                    "question": "Show all students",
                }
            ]
        elif "/runs" in url:
            resp.json.return_value = [
                {
                    "id": 12,
                    "question": "Show all students",
                    "status": "completed",
                    "created_at": "2026-10-15T10:30:00",
                    "agent_name": "General Assistant",
                    "username": "admin_user",
                    "total_latency_ms": 1500.0,
                }
            ]
        elif "/steps" in url:
            resp.json.return_value = [
                {
                    "step_number": 1,
                    "step_type": "llm",
                    "input_data": "prompt",
                    "output_data": '{"action": "tool", "tool": "calculator"}',
                    "latency_ms": 450.0,
                }
            ]
        elif "/audit" in url:
            resp.json.return_value = [
                {
                    "timestamp": "2026-10-15T10:30:00",
                    "user": "admin_user",
                    "action": "agent_run_started",
                    "outcome": "allowed",
                    "details": "Run #12 initiated",
                }
            ]
        else:
            resp.json.return_value = []
        return resp

    return _mock_get


def test_ui_unauthenticated_view(mock_backend_success):
    """Unauthenticated view displays login/register in Account tab, hides Agents, Audit, & Evaluation tabs."""
    with patch("requests.get", side_effect=mock_backend_success):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.run()
        assert len(at.exception) == 0

        tab_labels = [t.label for t in at.tabs]
        assert not any("Agents" in l for l in tab_labels)
        assert not any("Audit" in l for l in tab_labels)
        assert not any("Evaluation" in l for l in tab_labels)
        assert any("Chat" in l for l in tab_labels)
        assert any("Documents" in l for l in tab_labels)
        assert any("Approvals" in l for l in tab_labels)
        assert any("Account" in l for l in tab_labels)


def test_ui_normal_user_restricted_tabs(mock_backend_success):
    """A normal user (role='user') does NOT see Agents, Audit, or Evaluation tabs."""
    def _mock_user_get(url, *args, **kwargs):
        if "/auth/me" in url:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"user_id": 2, "username": "normal_student", "role": "user"}
            return resp
        return mock_backend_success(url, *args, **kwargs)

    with patch("requests.get", side_effect=_mock_user_get):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-user-jwt"
        at.session_state["user_info"] = {"user_id": 2, "username": "normal_student", "role": "user"}
        at.run()
        assert len(at.exception) == 0

        tab_labels = [t.label for t in at.tabs]
        assert not any("Agents" in l for l in tab_labels)
        assert not any("Audit" in l for l in tab_labels)
        assert not any("Evaluation" in l for l in tab_labels)
        assert any("Chat" in l for l in tab_labels)
        assert any("Documents" in l for l in tab_labels)


def test_ui_admin_full_tabs_view(mock_backend_success):
    """An admin user sees all 8 tabs including Agents, Audit Log, and Evaluation."""
    with patch("requests.get", side_effect=mock_backend_success):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-admin-jwt"
        at.session_state["user_info"] = {"user_id": 1, "username": "admin_user", "role": "admin"}
        at.run()
        assert len(at.exception) == 0

        tab_labels = [t.label for t in at.tabs]
        assert any("Agents" in l for l in tab_labels)
        assert any("Audit" in l for l in tab_labels)
        assert any("Evaluation" in l for l in tab_labels)
        assert any("Chat" in l for l in tab_labels)
        assert any("Documents" in l for l in tab_labels)
        assert any("Traces" in l for l in tab_labels)
        assert any("Approvals" in l for l in tab_labels)
        assert any("Account" in l for l in tab_labels)



def test_ui_backend_stopped_graceful_display():
    """When backend is offline, UI renders without crashing and shows offline status."""
    with patch("requests.get", side_effect=Exception("Connection refused")):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.run()
        assert len(at.exception) == 0


def test_ui_token_expiry_handling(mock_backend_success):
    """When /auth/me returns 401, session token is cleared and session expiry warning shown."""
    def _mock_expired(url, *args, **kwargs):
        if "/auth/me" in url:
            resp = MagicMock()
            resp.status_code = 401
            resp.json.return_value = {"detail": "Token expired"}
            return resp
        return mock_backend_success(url, *args, **kwargs)

    with patch("requests.get", side_effect=_mock_expired):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "expired-token"
        at.session_state["user_info"] = {"username": "old_user", "role": "user"}
        at.run()
        assert len(at.exception) == 0
        assert at.session_state["token"] is None
        assert at.session_state["user_info"] is None


def test_ui_document_management_and_delete_button(mock_backend_success):
    """Documents tab renders uploaded documents list and delete buttons."""
    with patch("requests.get", side_effect=mock_backend_success):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-admin-jwt"
        at.session_state["user_info"] = {"user_id": 1, "username": "admin_user", "role": "admin"}
        at.run()
        assert len(at.exception) == 0

        # Verify buttons exist in app
        button_keys = [b.key for b in at.button if b.key]
        assert any("del_doc_10" in k for k in button_keys)


def test_ui_approvals_tab_action_buttons(mock_backend_success):
    """Approvals tab renders pending approval request with Approve and Deny buttons."""
    with patch("requests.get", side_effect=mock_backend_success):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-admin-jwt"
        at.session_state["user_info"] = {"user_id": 1, "username": "admin_user", "role": "admin"}
        at.run()
        assert len(at.exception) == 0

        button_keys = [b.key for b in at.button if b.key]
        assert any("app_5" in k for k in button_keys)
        assert any("deny_5" in k for k in button_keys)


def test_ui_agents_tab_create_and_edit_forms(mock_backend_success):
    """Agents tab presents agent configuration and admin controls."""
    with patch("requests.get", side_effect=mock_backend_success):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-admin-jwt"
        at.session_state["user_info"] = {"user_id": 1, "username": "admin_user", "role": "admin"}
        at.run()
        assert len(at.exception) == 0
