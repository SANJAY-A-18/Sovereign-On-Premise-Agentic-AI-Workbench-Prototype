import pytest
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest

"""
Regression tests for Chat tab state lifecycle and run-result isolation:
- answered then abstention
- abstention then answered
- answered then Data Analyst (paused)
- denied then answered
"""

@pytest.fixture
def mock_lifecycle_backend():
    runs_db = {
        101: {
            "id": 101,
            "status": "completed",
            "question": "What is the book borrowing quota?",
            "final_answer": "Undergraduate students are allowed 4 books for 16 calendar days.",
            "total_latency_ms": 1420.5,
            "steps": [
                {
                    "step_number": 1,
                    "step_type": "tool",
                    "input_data": '{"action": "search_documents", "query": "quota"}',
                    "output_data": "[Source: library_rules.txt | Chunk #1]\nUndergraduate students are allowed 4 books for 16 calendar days.",
                    "latency_ms": 320.1,
                }
            ],
        },
        102: {
            "id": 102,
            "status": "completed",
            "question": "What is the blood donation policy?",
            "final_answer": "I do not know. The provided documents do not contain this information.",
            "total_latency_ms": 890.2,
            "steps": [],  # Clean abstention, no tools
        },
        103: {
            "id": 103,
            "status": "completed",
            "question": "What is the passing score percentage?",
            "final_answer": "The minimum passing percentage is 42% in written and 50% aggregate.",
            "total_latency_ms": 1150.0,
            "steps": [
                {
                    "step_number": 1,
                    "step_type": "tool",
                    "input_data": '{"action": "search_documents", "query": "passing score"}',
                    "output_data": "[Source: exam_regulations.txt | Chunk #2]\nPassing score is 42% in written examination and 50% in aggregate.",
                    "latency_ms": 290.4,
                }
            ],
        },
        201: {
            "id": 201,
            "status": "paused_for_approval",
            "question": "List students with GPA > 3.80",
            "final_answer": None,
            "total_latency_ms": 450.0,
            "steps": [
                {
                    "step_number": 1,
                    "step_type": "llm",
                    "input_data": "prompt",
                    "output_data": '{"action": "read_sql", "args": {"query": "SELECT * FROM students WHERE gpa > 3.80"}}',
                    "latency_ms": 450.0,
                }
            ],
        },
        202: {
            "id": 202,
            "status": "failed",
            "question": "DROP TABLE students",
            "final_answer": "Tool execution denied by human supervisor.",
            "total_latency_ms": 600.0,
            "steps": [
                {
                    "step_number": 1,
                    "step_type": "tool",
                    "input_data": "read_sql(DROP TABLE students)",
                    "output_data": "Tool execution was denied by human supervisor.",
                    "latency_ms": 0.0,
                }
            ],
        },
    }

    def _mock_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/auth/me" in url:
            resp.json.return_value = {"user_id": 2, "username": "testuser", "role": "user"}
        elif "/agents" in url and not "/run" in url:
            resp.json.return_value = [
                {"id": 1, "name": "Document Assistant", "model": "qwen2.5:3b", "allowed_tools": ["search_documents"], "system_prompt": "Doc Agent", "temperature": 0.2},
                {"id": 2, "name": "Data Analyst", "model": "qwen2.5:3b", "allowed_tools": ["read_sql"], "system_prompt": "Data Agent", "temperature": 0.2},
            ]
        elif "/runs/" in url:
            run_id = int(url.split("/runs/")[1].split("?")[0])
            if run_id in runs_db:
                resp.json.return_value = runs_db[run_id]
            else:
                resp.status_code = 404
                resp.json.return_value = {"detail": "Run not found"}
        elif "/approvals/pending" in url:
            resp.json.return_value = []
        elif "/documents" in url:
            resp.json.return_value = []
        elif "/runs" in url:
            resp.json.return_value = []
        elif "/health" in url:
            resp.json.return_value = {"status": "healthy", "ollama": {"reachable": True, "configured_chat_model": "qwen2.5:3b"}}
        else:
            resp.json.return_value = {}
        return resp

    return _mock_get, runs_db


def test_chat_lifecycle_answered_then_abstention(mock_lifecycle_backend):
    """
    Test 1: Run 1 is answered with citations. Run 2 is an abstention ('I do not know').
    Verifies that previous answer, citations, and status are completely cleared.
    """
    mock_get, _ = mock_lifecycle_backend

    def _mock_post(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"run_id": 102, "status": "completed"}
        return resp

    with patch("requests.get", side_effect=mock_get), patch("requests.post", side_effect=_mock_post):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-token"
        at.session_state["user_info"] = {"user_id": 2, "username": "testuser", "role": "user"}
        # Initial state: Run 101 was previously rendered
        at.session_state["latest_run_id"] = 101
        at.run()
        assert len(at.exception) == 0

        # Verify Run 101 is rendered
        md_text = " ".join([m.value for m in at.markdown])
        assert "Undergraduate students are allowed 4 books" in md_text
        assert "library_rules.txt" in md_text
        assert "Run `#101`" in md_text

        # Submit Question 2 (triggers Run 102 - abstention)
        at.text_area[0].input("What is the blood donation policy?").run()
        for b in at.button:
            if "Run Agent" in b.label:
                b.click().run()
                break

        assert len(at.exception) == 0
        md_after = " ".join([m.value for m in at.markdown])

        # Previous answer, citations, and run ID must NOT be present
        assert "Undergraduate students are allowed 4 books" not in md_after
        assert "library_rules.txt" not in md_after
        assert "Run `#101`" not in md_after

        # Current abstention answer and Run 102 heading must be present
        assert "I do not know" in md_after
        assert "Run `#102`" in md_after


def test_chat_lifecycle_abstention_then_answered(mock_lifecycle_backend):
    """
    Test 2: Run 1 is an abstention ('I do not know'). Run 2 is answered with citations.
    Verifies that the abstention text is cleared and the answered result is rendered.
    """
    mock_get, _ = mock_lifecycle_backend

    def _mock_post(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"run_id": 103, "status": "completed"}
        return resp

    with patch("requests.get", side_effect=mock_get), patch("requests.post", side_effect=_mock_post):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-token"
        at.session_state["user_info"] = {"user_id": 2, "username": "testuser", "role": "user"}
        # Initial state: Run 102 (abstention) was previously rendered
        at.session_state["latest_run_id"] = 102
        at.run()
        assert len(at.exception) == 0

        md_text = " ".join([m.value for m in at.markdown])
        assert "I do not know" in md_text
        assert "Run `#102`" in md_text

        # Submit Question 3 (triggers Run 103 - answered)
        at.text_area[0].input("What is the passing score percentage?").run()
        for b in at.button:
            if "Run Agent" in b.label:
                b.click().run()
                break

        assert len(at.exception) == 0
        md_after = " ".join([m.value for m in at.markdown])

        # Abstention from Run 102 must be gone
        assert "I do not know" not in md_after
        assert "Run `#102`" not in md_after

        # Answered content from Run 103 must be rendered
        assert "minimum passing percentage is 42%" in md_after
        assert "exam_regulations.txt" in md_after
        assert "Run `#103`" in md_after


def test_chat_lifecycle_answered_then_data_analyst(mock_lifecycle_backend):
    """
    Test 3: Run 1 is an answered Document Assistant query. Run 2 is a Data Analyst query that pauses for approval.
    Verifies that Document Assistant answer/citations are cleared, and the waiting-for-approval banner is shown.
    """
    mock_get, _ = mock_lifecycle_backend

    def _mock_post(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"run_id": 201, "status": "paused_for_approval"}
        return resp

    with patch("requests.get", side_effect=mock_get), patch("requests.post", side_effect=_mock_post):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-token"
        at.session_state["user_info"] = {"user_id": 2, "username": "testuser", "role": "user"}
        at.session_state["latest_run_id"] = 101
        at.run()
        assert len(at.exception) == 0

        # Switch agent to Data Analyst and run query
        at.selectbox[0].select("Data Analyst").run()
        at.text_area[0].input("List students with GPA > 3.80").run()
        for b in at.button:
            if "Run Agent" in b.label:
                b.click().run()
                break

        assert len(at.exception) == 0
        md_after = " ".join([m.value for m in at.markdown])

        # Old Document Assistant answer and citations must NOT be present
        assert "Undergraduate students are allowed 4 books" not in md_after
        assert "library_rules.txt" not in md_after
        assert "Run `#101`" not in md_after

        # Paused approval banner and Run 201 ID must be present
        assert "Waiting for approval" in md_after
        assert "Run `#201`" in md_after


def test_chat_lifecycle_denied_then_answered(mock_lifecycle_backend):
    """
    Test 4: Run 1 was a denied Data Analyst query. Run 2 is an answered Document Assistant query.
    Verifies that supervisor denial message and failed status are cleared when the new query runs.
    """
    mock_get, _ = mock_lifecycle_backend

    def _mock_post(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"run_id": 101, "status": "completed"}
        return resp

    with patch("requests.get", side_effect=mock_get), patch("requests.post", side_effect=_mock_post):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-token"
        at.session_state["user_info"] = {"user_id": 2, "username": "testuser", "role": "user"}
        # Initial state: Run 202 (denied)
        at.session_state["latest_run_id"] = 202
        at.run()
        assert len(at.exception) == 0

        # Verify denied message is shown
        warning_text = " ".join([w.value for w in at.warning])
        assert "denied by human supervisor" in warning_text.lower()
        md_text = " ".join([m.value for m in at.markdown])
        assert "Run `#202`" in md_text

        # Run Document Assistant question
        at.selectbox[0].select("Document Assistant").run()
        at.text_area[0].input("What is the book borrowing quota?").run()
        for b in at.button:
            if "Run Agent" in b.label:
                b.click().run()
                break

        assert len(at.exception) == 0

        # Verify denial warning is gone
        warning_after = " ".join([w.value for w in at.warning])
        assert "denied by human supervisor" not in warning_after.lower()

        # Verify Run 101 completed answer is present
        md_after = " ".join([m.value for m in at.markdown])
        assert "Run `#202`" not in md_after
        assert "Undergraduate students are allowed 4 books" in md_after
        assert "Run `#101`" in md_after


def test_m4_approvals_banner_dismiss(mock_lifecycle_backend):
    """M-4: Verify Approvals tab recent decision banner can be cleanly dismissed."""
    mock_get, _ = mock_lifecycle_backend

    with patch("requests.get", side_effect=mock_get):
        at = AppTest.from_file("ui/app.py", default_timeout=15)
        at.session_state["token"] = "valid-token"
        at.session_state["user_info"] = {"user_id": 1, "username": "admin", "role": "admin"}
        at.session_state["last_approval_decision"] = {
            "id": 1,
            "decision": "approved",
            "run_id": 201,
        }
        at.run()

        # Check banner exists in info messages
        info_text = " ".join([i.value for i in at.info])
        assert "Recent Decision Outcome" in info_text
        assert "Request `#1` was **APPROVED**" in info_text

        # Click dismiss button
        dismiss_btn = None
        for b in at.button:
            if "Dismiss" in b.label:
                dismiss_btn = b
                break
        assert dismiss_btn is not None
        dismiss_btn.click().run()

        # Banner should now be dismissed
        info_text_after = " ".join([i.value for i in at.info])
        assert "Recent Decision Outcome" not in info_text_after
        assert at.session_state["last_approval_decision"] is None


