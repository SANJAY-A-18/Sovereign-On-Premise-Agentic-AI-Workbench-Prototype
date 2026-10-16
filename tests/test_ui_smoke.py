"""
UI Smoke tests using streamlit.testing.v1.AppTest for ui/app.py.
Exercises:
- Unauthenticated / login view
- Normal user: chat, documents, and approvals tabs
- Role-based tab visibility: Agents and Audit tabs are hidden for normal users, visible for admin
- Asserts zero exceptions during rendering
"""

import pytest
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest


@pytest.fixture(autouse=True)
def mock_backend_requests():
    """Mock HTTP requests to backend so UI smoke tests execute quickly without waiting on dead sockets."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    with patch("requests.get", return_value=mock_resp), patch("requests.post", return_value=mock_resp):
        yield


def test_ui_unauthenticated_smoke():
    """Verify unauthenticated user view loads cleanly with zero exceptions."""
    at = AppTest.from_file("ui/app.py", default_timeout=15)
    at.run()
    assert len(at.exception) == 0

    tab_labels = [t.label for t in at.tabs]
    # Normal/unauthenticated user must NOT see Agents or Audit Log tabs
    assert not any("Agents" in label for label in tab_labels)
    assert not any("Audit" in label for label in tab_labels)
    # Must see Chat, Documents, Approvals, and Account
    assert any("Chat" in label for label in tab_labels)
    assert any("Documents" in label for label in tab_labels)
    assert any("Approvals" in label for label in tab_labels)
    assert any("Account" in label for label in tab_labels)


def test_ui_normal_user_smoke():
    """Verify normal user view: Agents and Audit tabs are hidden, zero exceptions."""
    at = AppTest.from_file("ui/app.py", default_timeout=15)
    at.session_state["token"] = "fake-jwt-token-for-user"
    at.session_state["user_info"] = {
        "user_id": 2,
        "username": "student_user",
        "role": "user",
    }
    at.run()
    assert len(at.exception) == 0

    tab_labels = [t.label for t in at.tabs]
    assert not any("Agents" in label for label in tab_labels)
    assert not any("Audit" in label for label in tab_labels)
    assert any("Chat" in label for label in tab_labels)
    assert any("Documents" in label for label in tab_labels)
    assert any("Approvals" in label for label in tab_labels)


def test_ui_admin_user_smoke():
    """Verify admin user view: Agents and Audit tabs are visible, zero exceptions."""
    at = AppTest.from_file("ui/app.py", default_timeout=15)
    at.session_state["token"] = "fake-jwt-token-for-admin"
    at.session_state["user_info"] = {
        "user_id": 1,
        "username": "system_admin",
        "role": "admin",
    }
    at.run()
    assert len(at.exception) == 0

    tab_labels = [t.label for t in at.tabs]
    assert any("Agents" in label for label in tab_labels)
    assert any("Audit" in label for label in tab_labels)
