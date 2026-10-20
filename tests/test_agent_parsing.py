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


# ==============================================================================
# Post-Evaluation Tests: Argument Normalization Unwrapping (Bug Fix 1)
# ==============================================================================

@pytest.mark.parametrize(
    "payload, expected_query",
    [
        # 1. args as dict
        ('{"action": "tool", "tool": "search_documents", "args": {"query": "sample query"}}', "sample query"),
        # 2. args as JSON string
        ('{"action": "tool", "tool": "search_documents", "args": "{\\"query\\": \\"sample query\\"}"}', "sample query"),
        # 3. arguments as dict
        ('{"action": "tool", "tool": "search_documents", "arguments": {"query": "sample query"}}', "sample query"),
        # 4. arguments as JSON string
        ('{"action": "tool", "tool": "search_documents", "arguments": "{\\"query\\": \\"sample query\\"}"}', "sample query"),
        # 5. parameters as dict
        ('{"action": "tool", "tool": "search_documents", "parameters": {"query": "sample query"}}', "sample query"),
        # 6. parameters as JSON string
        ('{"action": "tool", "tool": "search_documents", "parameters": "{\\"query\\": \\"sample query\\"}"}', "sample query"),
        # 7. params as dict
        ('{"action": "tool", "tool": "search_documents", "params": {"query": "sample query"}}', "sample query"),
        # 8. params as JSON string
        ('{"action": "tool", "tool": "search_documents", "params": "{\\"query\\": \\"sample query\\"}"}', "sample query"),
        # 9. input as dict
        ('{"action": "tool", "tool": "search_documents", "input": {"query": "sample query"}}', "sample query"),
        # 10. input as JSON string
        ('{"action": "tool", "tool": "search_documents", "input": "{\\"query\\": \\"sample query\\"}"}', "sample query"),
        # 11. input as raw string
        ('{"action": "tool", "tool": "search_documents", "input": "sample query"}', "sample query"),
        # 12. args with trailing colon
        ('{"action": "tool", "tool": "search_documents", "args:": {"query": "sample query"}}', "sample query"),
        # 13. parameters with trailing colon
        ('{"action": "tool", "tool": "search_documents", "parameters:": {"query": "sample query"}}', "sample query"),
        # 14. direct tool name with wrapped args
        ('{"action": "search_documents", "args:": {"query": "sample query"}}', "sample query"),
        # 15. direct tool name with nested wrapper
        ('{"action": "search_documents", "args": {"parameters": {"query": "sample query"}}}', "sample query"),
        # 16. nested wrapper keys
        ('{"action": "tool", "tool": "search_documents", "args": {"args": {"query": "sample query"}}}', "sample query"),
        ('{"action": "tool", "tool": "search_documents", "args": {"arguments": "{\\"query\\": \\"sample query\\"}"}}', "sample query"),
    ],
)
def test_all_wrapper_shapes(payload, expected_query):
    parsed = extract_json_from_llm(payload)
    action_type, action_data = validate_agent_action(parsed)
    assert action_type == "tool"
    assert action_data["tool"] == "search_documents"
    assert action_data["args"].get("query") == expected_query
    # Crucially ensure NO wrapper keys remain in args
    for k in ["args", "args:", "arguments", "parameters", "params", "input"]:
        assert k not in action_data["args"]


def test_regression_sample_policy_queries(monkeypatch):
    """
    Regression test using the exact prompts:
    - 'How many days can I borrow a book and what is the overdue fine?'
    - 'What is the hostel curfew time?'
    against sample_policy.txt with mocked LLM output producing wrapped args.
    Verifies that search_documents does not fail with 'unexpected keyword argument'.
    """
    import json
    from pathlib import Path
    from backend.agent import AgentRunner
    from backend.db import SessionLocal, User, Agent, Run, Step
    from backend.llm import ollama_client
    from backend.rag import vector_store

    # 1. Ingest sample_policy.txt into the isolated vector store
    sample_policy_path = Path("data/uploads/sample_policy.txt")
    assert sample_policy_path.exists(), "sample_policy.txt must exist"
    policy_content = sample_policy_path.read_text(encoding="utf-8")

    # Mock embedding function returning dummy deterministic vector
    def mock_embed(texts):
        if isinstance(texts, str):
            return [0.05] * 768
        return [[0.05] * 768 for _ in texts]

    monkeypatch.setattr(ollama_client, "embed", mock_embed)

    vector_store.add_document(
        document_id=999,
        filename="sample_policy.txt",
        chunks=[policy_content],
        embedding_fn=mock_embed,
    )

    db = SessionLocal()
    try:
        user = User(username="regression_user", password_hash="dummy", role="admin")
        db.add(user)
        db.commit()

        agent = Agent(
            name="Policy Bot",
            system_prompt="You are a policy assistant.",
            model="qwen2.5:3b",
            temperature=0.0,
            allowed_tools=json.dumps(["search_documents"]),
        )
        db.add(agent)
        db.commit()

        test_cases = [
            {
                "prompt": "How many days can I borrow a book and what is the overdue fine?",
                # Emits wrapper key {"action": "search_documents", "args:": {"query": ...}}
                "turn1": json.dumps({
                    "action": "search_documents",
                    "args:": {"query": "How many days can I borrow a book and what is the overdue fine?"}
                }),
                "turn2": json.dumps({
                    "action": "final",
                    "answer": "Books may be borrowed for 14 days and the overdue fine is Rs 5 per day."
                }),
                "expected_answer_part": "14 days",
            },
            {
                "prompt": "What is the hostel curfew time?",
                # Emits wrapper key {"tool": "search_documents", "args": {"args": {"query": ...}}}
                "turn1": json.dumps({
                    "action": "tool",
                    "tool": "search_documents",
                    "args": {"args": {"query": "What is the hostel curfew time?"}}
                }),
                "turn2": json.dumps({
                    "action": "final",
                    "answer": "The provided policy does not mention any hostel curfew time."
                }),
                "expected_answer_part": "hostel curfew",
            },
        ]

        for tc in test_cases:
            call_count = [0]
            turn1_resp = tc["turn1"]
            turn2_resp = tc["turn2"]

            def mock_chat(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    return turn1_resp
                return turn2_resp

            monkeypatch.setattr(ollama_client, "chat", mock_chat)

            run = Run(
                user_id=user.id,
                agent_id=agent.id,
                question=tc["prompt"],
                status="pending",
            )
            db.add(run)
            db.commit()

            result = AgentRunner.run_agent(run.id, db)
            assert result["status"] == "completed"
            assert tc["expected_answer_part"] in result["answer"]

            # Assert no step in this run had an unexpected keyword argument error
            steps = db.query(Step).filter(Step.run_id == run.id).all()
            for s in steps:
                assert "unexpected keyword argument" not in (s.output_data or ""), (
                    f"Unexpected keyword argument error found in step #{s.step_number}: {s.output_data}"
                )
                if s.step_type == "tool":
                    assert not s.output_data.startswith("Tool Execution Error"), (
                        f"Tool failed: {s.output_data}"
                    )
    finally:
        db.close()

