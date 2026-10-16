"""
Evaluation metrics for Sovereign AI Workbench Benchmark.
Pure functions with zero external LLM dependencies, fully unit-tested.
Includes:
- tool_call_valid: verifies first LLM reply is schema-correct JSON
- task_success: checks tool invocation, answer match, and abstention on decoys
- retrieval_hit: checks presence of target file in top-k chunks
- citation_valid: checks cited files and chunk indices against corpus
- wilson_score_interval: 95% confidence intervals for proportions
- mcnemar_exact: exact two-sided McNemar test using math.comb (standard library only)
"""

import math
import re
from typing import Dict, Any, List, Optional, Tuple, Union


ABSTENTION_PHRASES = [
    "do not know",
    "don't know",
    "not mention",
    "no information",
    "cannot find",
    "not found",
    "not provided",
    "does not contain",
    "do not contain",
    "no relevant",
    "unable to find",
    "not have enough information",
    "not enough information",
    "not stated",
    "not specify",
]


def is_abstention(text: str) -> bool:
    """Checks whether the text acknowledges that the requested information is absent."""
    if not text:
        return False
    lower = text.lower()
    return any(phrase in lower for phrase in ABSTENTION_PHRASES)


def compute_tool_call_valid(raw_llm_response: str) -> bool:
    """
    Validates whether the raw first LLM reply parses to a valid agent action
    (either Schema A 'tool' or Schema B 'final') on the first attempt without retries.
    """
    from backend.agent import extract_json_from_llm, validate_agent_action

    if not raw_llm_response or not raw_llm_response.strip():
        return False
    try:
        parsed_dict = extract_json_from_llm(raw_llm_response)
        action_type, _ = validate_agent_action(parsed_dict)
        return action_type in ("tool", "final")
    except Exception:
        return False


def compute_retrieval_hit(
    retrieved_chunks: List[Dict[str, Any]],
    expected_source_file: str,
    top_k: int = 3,
) -> bool:
    """
    Checks if the expected source file appears in the top-k retrieved chunks.
    """
    if not expected_source_file:
        return False
    target = expected_source_file.strip().lower()
    for chunk in retrieved_chunks[:top_k]:
        filename = (chunk.get("filename") or "").lower()
        if target in filename or filename in target:
            return True
    return False


def compute_citation_valid(
    answer: str,
    sources: List[str],
    corpus_metadata: Dict[str, int],
) -> bool:
    """
    Validates citations in the answer and recorded source strings against corpus metadata.
    corpus_metadata maps lowercase filename -> total chunk count.
    Returns False if any cited file does not exist in the corpus or chunk index is out of bounds.
    Returns True if citations are valid or if no explicit citation was asserted.
    """
    combined_text = f"{answer} {' '.join(sources)}"
    
    # Check for file references: e.g. attendance_rules.txt, exam_regulations.txt, library_rules.txt
    file_pattern = re.compile(r'([\w\-]+\.(?:txt|pdf|docx))', re.IGNORECASE)
    referenced_files = set(file_pattern.findall(combined_text))

    if not referenced_files:
        # No file citation was made
        return True

    for rf in referenced_files:
        rf_lower = rf.lower()
        matching_key = None
        for k in corpus_metadata.keys():
            if k.lower() == rf_lower:
                matching_key = k
                break
        if matching_key is None:
            # Hallucinated file
            return False

        # Optional chunk index check if present in text e.g. "chunk 2" or "chunk_index: 2"
        chunk_patterns = [
            rf_lower + r'[\s\w,:]*chunk\s*(\d+)',
            r'chunk\s*(\d+)[\s\w,:]*' + rf_lower,
        ]
        for cp in chunk_patterns:
            for match in re.finditer(cp, combined_text.lower()):
                idx = int(match.group(1))
                max_chunks = corpus_metadata.get(matching_key, 999999)
                if idx < 0 or idx >= max_chunks:
                    return False

    return True


def compute_task_success(
    expected_tool: Optional[str],
    used_tools: List[str],
    answer: str,
    answerable: bool = True,
    ground_truth: Optional[Union[str, int, float]] = None,
    expected_keywords: Optional[List[str]] = None,
    match_mode: str = "all",
) -> bool:
    """
    Determines task success:
    1. For unanswerable items (answerable=False):
       Success = agent abstains (states it does not know) and does not invent facts.
    2. For answerable items:
       - Expected tool was invoked (if expected_tool is specified).
       - Answer matches ground truth or expected keywords according to match_mode.
    """
    if not answerable:
        return is_abstention(answer)

    # 1. Tool check
    if expected_tool:
        tool_used = any(expected_tool.lower() == t.lower() for t in used_tools)
        if not tool_used:
            return False

    ans_clean = answer.strip()
    if not ans_clean:
        return False

    # 2. Ground truth check (numerical / exact)
    if ground_truth is not None:
        if isinstance(ground_truth, (int, float)):
            # Check numerical equivalence or presence
            gt_int = int(ground_truth)
            gt_str_int = str(gt_int)
            gt_str_float = f"{float(ground_truth):.2f}".rstrip("0").rstrip(".")
            # Look for number in answer
            found_num = False
            # Check direct string match
            if gt_str_int in ans_clean or gt_str_float in ans_clean:
                found_num = True
            else:
                # Find all numbers in answer and compare
                numbers_in_ans = re.findall(r"[-+]?\d*\.?\d+", ans_clean.replace(",", ""))
                for n in numbers_in_ans:
                    try:
                        val = float(n)
                        if math.isclose(val, float(ground_truth), rel_tol=1e-2, abs_tol=1e-2):
                            found_num = True
                            break
                    except ValueError:
                        pass
            if not found_num:
                return False
        else:
            # String ground truth
            gt_str = str(ground_truth).strip().lower()
            if gt_str not in ans_clean.lower():
                return False

    # 3. Keyword check
    if expected_keywords:
        lower_ans = ans_clean.lower()
        if match_mode.lower() == "any":
            if not any(k.lower() in lower_ans for k in expected_keywords):
                return False
        else:  # "all"
            if not all(k.lower() in lower_ans for k in expected_keywords):
                return False

    return True


def compute_wilson_ci(
    successes: int,
    total: int,
    confidence: float = 0.95,
) -> Tuple[float, float, float]:
    """
    Computes Wilson score confidence interval for a binomial proportion.
    Returns (point_estimate, ci_lower, ci_upper).
    Uses standard normal critical value z = 1.95996 for 95% confidence.
    """
    if total <= 0:
        return (0.0, 0.0, 0.0)

    p = successes / total
    # z value for two-sided confidence: 1.95996 for 95%
    z = 1.959963984540054
    if abs(confidence - 0.90) < 0.01:
        z = 1.6448536269514722
    elif abs(confidence - 0.99) < 0.01:
        z = 2.5758293035489004

    z2 = z * z
    denominator = 1.0 + z2 / total
    centre = (p + z2 / (2.0 * total)) / denominator
    spread = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total) / denominator

    lower = max(0.0, centre - spread)
    upper = min(1.0, centre + spread)
    return (round(p, 4), round(lower, 4), round(upper, 4))


def compute_mcnemar_exact(b: int, c: int) -> Tuple[int, int, float]:
    """
    Computes exact two-sided McNemar test for paired binary observations.
    b: Number of items where condition 1 failed (0) and condition 2 succeeded (1).
    c: Number of items where condition 1 succeeded (1) and condition 2 failed (0).
    Uses standard library math.comb for exact binomial calculation under H0: p=0.5.
    Returns (b, c, p_value).
    """
    n_discordant = b + c
    if n_discordant == 0:
        return (b, c, 1.0)

    k = min(b, c)
    # Two-sided binomial probability with p=0.5
    prob_sum = 0.0
    for i in range(k + 1):
        prob_sum += math.comb(n_discordant, i) * (0.5 ** n_discordant)

    p_value = min(1.0, 2.0 * prob_sum)
    return (b, c, round(p_value, 5))
