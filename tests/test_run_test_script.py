"""
Unit tests for the scripts/run_test_script.py automated test suite runner.
Verifies that the test runner executes cleanly against an isolated temporary environment.
"""

import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_test_script import TestScriptRunner, TestCaseResult


def test_test_case_result_serialization():
    res = TestCaseResult(
        check_id="T1",
        title="Sample Test",
        category="TestCat",
        status="PASS",
        details="Sample details",
        automated=True,
    )
    d = res.to_dict()
    assert d["check_id"] == "T1"
    assert d["status"] == "PASS"
    assert d["automated"] is True


def test_runner_offline_execution_pass():
    runner = TestScriptRunner(live=False, verbose=False)
    runner.setup_isolated_environment()
    try:
        runner.run_all_checks()
        pass_cnt, fail_cnt, skip_cnt = runner.print_summary_table()
        assert fail_cnt == 0, f"Expected 0 failures in offline test script run, got {fail_cnt}"
        assert pass_cnt > 20, f"Expected at least 20 passed checks, got {pass_cnt}"
        assert skip_cnt >= 4, f"Expected at least 4 skipped checks (live/manual), got {skip_cnt}"
    finally:
        runner.teardown_environment()
