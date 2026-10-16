"""
Unit tests for the forgiving agent output JSON parser and action validator.
Ensures small models producing imperfect outputs (fences, commentary, trailing commas)
are parsed accurately without failing runs.
Runs completely offline without Ollama.
"""

import pytest
from backend.agent import extract_json_from_llm, validate_agent_action


def test_clean_tool_json():
    raw = '{"action": "tool", "tool": "calculator", "args": {"expression": "24 * 7"}}'
    parsed = extract_json_from_llm(raw)
    action_type, action_data = validate_agent_action(parsed)
    assert action_type == "tool"
    assert action_data["tool"] == "calculator"
    assert action_data["args"] == {"expression": "24 * 7"}


def test_markdown_fenced_json():
    raw = """Here is my plan:
```json
{
  "action": "tool",
  "tool": "search_documents",
  "args": {
    "query": "quarterly revenue"
  }
}
```
Please let me know if you need more."""
    parsed = extract_json_from_llm(raw)
    action_type, action_data = validate_agent_action(parsed)
    assert action_type == "tool"
    assert action_data["tool"] == "search_documents"
    assert action_data["args"]["query"] == "quarterly revenue"


def test_plain_code_fenced_json():
    raw = """```
{
  "action": "final",
  "answer": "The total student count is 10."
}
```"""
    parsed = extract_json_from_llm(raw)
    action_type, action_data = validate_agent_action(parsed)
    assert action_type == "final"
    assert "total student count is 10" in action_data["answer"]


def test_json_with_trailing_commas():
    # Small models frequently leave trailing commas
    raw = """
    {
      "action": "tool",
      "tool": "calculator",
      "args": {
        "expression": "100 / 4",
      },
    }
    """
    parsed = extract_json_from_llm(raw)
    action_type, action_data = validate_agent_action(parsed)
    assert action_type == "tool"
    assert action_data["tool"] == "calculator"
    assert action_data["args"]["expression"] == "100 / 4"


def test_json_with_colon_args_variation():
    raw = '{"action": "tool", "tool": "search_documents", "args:": {"query": "What is the minimum attendance?"}}'
    parsed = extract_json_from_llm(raw)
    action_type, action_data = validate_agent_action(parsed)
    assert action_type == "tool"
    assert action_data["tool"] == "search_documents"
    assert action_data["args"] == {"query": "What is the minimum attendance?"}


def test_json_surrounded_by_chatter():
    raw = """Sure, I would be happy to help! Let me invoke the file reader:
    {"action": "tool", "tool": "read_file", "args": {"filename": "data.txt"}}
    I will report back with the result soon."""
    parsed = extract_json_from_llm(raw)
    action_type, action_data = validate_agent_action(parsed)
    assert action_type == "tool"
    assert action_data["tool"] == "read_file"
    assert action_data["args"]["filename"] == "data.txt"


def test_invalid_json_raises_value_error():
    with pytest.raises(ValueError):
        extract_json_from_llm("I cannot find any data and I don't know how to format JSON.")


def test_invalid_schema_action():
    bad_data = {"action": "unknown_action", "something": 123}
    with pytest.raises(ValueError) as excinfo:
        validate_agent_action(bad_data)
    assert "Unrecognized action" in str(excinfo.value)
