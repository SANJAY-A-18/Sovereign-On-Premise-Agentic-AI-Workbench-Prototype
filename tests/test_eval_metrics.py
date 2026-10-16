"""
Unit tests for eval/metrics.py.
Pure offline tests requiring zero Ollama connection.
Verifies tool call validation, task success, retrieval hit, citation check,
Wilson confidence intervals, and exact McNemar calculations.
"""

import math
import pytest
from eval.metrics import (
    compute_tool_call_valid,
    compute_retrieval_hit,
    compute_citation_valid,
    is_abstention,
    compute_task_success,
    compute_wilson_ci,
    compute_mcnemar_exact,
)


def test_tool_call_valid():
    # Valid Schema A (tool call)
    valid_tool = '{"action": "tool", "tool": "calculator", "args": {"expression": "2+2"}}'
    assert compute_tool_call_valid(valid_tool) is True

    # Valid Schema B (final answer)
    valid_final = '{"action": "final", "answer": "The minimum attendance is 82%."}'
    assert compute_tool_call_valid(valid_final) is True

    # Valid with markdown fences
    valid_fenced = '```json\n{"action": "tool", "tool": "search_documents", "args": {"query": "fees"}}\n```'
    assert compute_tool_call_valid(valid_fenced) is True

    # Invalid / plain conversational text
    assert compute_tool_call_valid("Sure, let me help you calculate 2+2.") is False
    assert compute_tool_call_valid("") is False

    # Broken JSON boundaries
    assert compute_tool_call_valid('{"action": "tool", "tool": "calculator"') is False


def test_retrieval_hit():
    chunks = [
        {"filename": "attendance_rules.txt", "chunk_index": 0},
        {"filename": "exam_regulations.txt", "chunk_index": 1},
        {"filename": "library_rules.txt", "chunk_index": 0},
        {"filename": "other_rules.txt", "chunk_index": 0},
    ]

    # Hit within top 3
    assert compute_retrieval_hit(chunks, "attendance_rules.txt", top_k=3) is True
    assert compute_retrieval_hit(chunks, "library_rules.txt", top_k=3) is True

    # 4th item not in top 3
    assert compute_retrieval_hit(chunks, "other_rules.txt", top_k=3) is False
    # But in top 4
    assert compute_retrieval_hit(chunks, "other_rules.txt", top_k=4) is True

    # Missing file
    assert compute_retrieval_hit(chunks, "nonexistent.txt", top_k=3) is False


def test_citation_valid():
    corpus = {
        "attendance_rules.txt": 3,
        "exam_regulations.txt": 4,
        "library_rules.txt": 2,
    }

    # Valid citation in answer
    ans_valid = "Based on attendance_rules.txt (chunk 1), attendance is 82%."
    assert compute_citation_valid(ans_valid, [], corpus) is True

    # Valid citation in sources list
    assert compute_citation_valid("Attendance is 82%", ["Source: library_rules.txt chunk 0"], corpus) is True

    # Hallucinated file
    ans_hallucinated = "According to secret_guidelines.txt, attendance is 70%."
    assert compute_citation_valid(ans_hallucinated, [], corpus) is False

    # Out of bounds chunk index (library_rules has 2 chunks: indices 0 and 1)
    ans_bad_chunk = "Based on library_rules.txt chunk 99, fines are Rs 40."
    assert compute_citation_valid(ans_bad_chunk, [], corpus) is False


def test_is_abstention():
    assert is_abstention("I do not know the answer based on provided documents.") is True
    assert is_abstention("The provided documents do not contain information on blood donation.") is True
    assert is_abstention("No information was found regarding the query.") is True
    assert is_abstention("The minimum attendance is 82 percent.") is False
    assert is_abstention("") is False


def test_task_success():
    # Calculator task success
    calc_ok = compute_task_success(
        expected_tool="calculator",
        used_tools=["calculator"],
        answer="The total calculated amount is 20720.",
        answerable=True,
        ground_truth=20720.0,
    )
    assert calc_ok is True

    # Calculator wrong tool
    calc_wrong_tool = compute_task_success(
        expected_tool="calculator",
        used_tools=["search_documents"],
        answer="The total calculated amount is 20720.",
        answerable=True,
        ground_truth=20720.0,
    )
    assert calc_wrong_tool is False

    # Calculator wrong answer
    calc_wrong_ans = compute_task_success(
        expected_tool="calculator",
        used_tools=["calculator"],
        answer="The answer is 15000.",
        answerable=True,
        ground_truth=20720.0,
    )
    assert calc_wrong_ans is False

    # SQL task success with string ground truth
    sql_ok = compute_task_success(
        expected_tool="read_sql",
        used_tools=["read_sql"],
        answer="The student in Biotechnology is Meera Nair.",
        answerable=True,
        ground_truth="Meera Nair",
    )
    assert sql_ok is True

    # Document keyword matching (all vs any)
    doc_all_ok = compute_task_success(
        expected_tool="search_documents",
        used_tools=["search_documents"],
        answer="The fee is Rs 1,150 per theoretical credit.",
        answerable=True,
        expected_keywords=["1,150", "credit"],
        match_mode="all",
    )
    assert doc_all_ok is True

    doc_all_fail = compute_task_success(
        expected_tool="search_documents",
        used_tools=["search_documents"],
        answer="The fee is Rs 1,150.",
        answerable=True,
        expected_keywords=["1,150", "credit"],
        match_mode="all",
    )
    assert doc_all_fail is False

    doc_any_ok = compute_task_success(
        expected_tool="search_documents",
        used_tools=["search_documents"],
        answer="The fee is 2450.",
        answerable=True,
        expected_keywords=["2,450", "2450"],
        match_mode="any",
    )
    assert doc_any_ok is True

    # Unanswerable item: should abstain
    decoy_pass = compute_task_success(
        expected_tool=None,
        used_tools=["search_documents"],
        answer="I do not know. The documents do not contain information on blood donation.",
        answerable=False,
    )
    assert decoy_pass is True

    decoy_fail = compute_task_success(
        expected_tool=None,
        used_tools=["search_documents"],
        answer="Students receive 5 percent attendance relief for blood donation.",
        answerable=False,
    )
    assert decoy_fail is False


def test_wilson_ci():
    # 0 / 10
    pt, low, high = compute_wilson_ci(0, 10)
    assert pt == 0.0
    assert low == 0.0
    assert high > 0.0

    # 10 / 10
    pt, low, high = compute_wilson_ci(10, 10)
    assert pt == 1.0
    assert low < 1.0
    assert high == 1.0

    # 5 / 10 (point estimate 0.5)
    pt, low, high = compute_wilson_ci(5, 10)
    assert pt == 0.5
    assert 0.0 < low < 0.5
    assert 0.5 < high < 1.0

    # Empty
    assert compute_wilson_ci(0, 0) == (0.0, 0.0, 0.0)


def test_mcnemar_exact():
    # Identical performance: discordant pairs = (0, 0) -> p = 1.0
    b, c, p = compute_mcnemar_exact(0, 0)
    assert p == 1.0

    # Symmetrical discordance: (2, 2) -> p = 1.0
    b, c, p = compute_mcnemar_exact(2, 2)
    assert p == 1.0

    # Heavy skew: 0 vs 10 discordant pairs -> very small p
    b, c, p = compute_mcnemar_exact(0, 10)
    assert b == 0 and c == 10
    # 2 * (0.5^10) = 2 / 1024 ~ 0.00195
    assert p < 0.01
