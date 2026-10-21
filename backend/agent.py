"""
Agent execution loop for Sovereign Workbench.
Hand-crafted agent loop without LangChain or LlamaIndex.
Features:
- Prompt synthesis with allowed tools schemas
- Forgiving JSON extraction (handles code fences, trailing commas, surrounding text)
- Configurable retry logic (ENABLE_RETRY flag)
- Step-by-step latency tracking in SQLite
- Policy enforcement and human-in-the-loop pause/resume for high-risk actions
- Source/citation tracking
"""

import json
import re
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import Run, Step, Agent, User, Approval
from backend.llm import ollama_client, OllamaError
from backend.tools import tool_registry
from backend.policy import evaluate_policy, PolicyDecision


def extract_json_from_llm(raw: str) -> Dict[str, Any]:
    """
    Forgiving parser to extract a single JSON object from messy LLM text.
    Handles markdown fences (```json ... ```), surrounding conversational text,
    newlines, and trailing commas.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty LLM response received.")

    cleaned = raw.strip()

    # If wrapped in code blocks, extract inner content
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()

    # Locate first '{' and last '}'
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace < first_brace:
        raise ValueError("No JSON object boundaries '{' ... '}' found in LLM response.")

    candidate = cleaned[first_brace : last_brace + 1].strip()

    # 1. Try direct standard JSON parsing
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 2. Fix trailing commas before closing braces/brackets (common small LLM issue)
    fixed = re.sub(r",\s*([\}\]])", r"\1", candidate)
    try:
        parsed = json.loads(fixed)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 3. Handle unescaped newlines within strings
    fixed_newlines = re.sub(
        r'("(?:[^"\\]|\\.)*")',
        lambda m: m.group(1).replace('\n', '\\n').replace('\r', '\\r'),
        fixed
    )
    try:
        parsed = json.loads(fixed_newlines)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON structure in LLM response: {str(e)}")

    raise ValueError("Extracted JSON root is not an object/dictionary.")


WRAPPER_KEYS = {"args", "arguments", "parameters", "params", "input"}


def clean_wrapper_key(k: str) -> str:
    """Normalize potential wrapper key by stripping leading/trailing whitespace, colons, and open braces."""
    return str(k).strip().rstrip(":{ \t").strip().lower()


def unwrap_tool_args(args: Any, tool_name: Optional[str] = None) -> Any:
    """
    Recursively unwrap wrapper keys (args, arguments, parameters, params, input),
    whether provided as dictionaries or JSON strings, including keys with trailing colons
    or opening braces like 'args: {'.
    """
    clean_tool = (tool_name or "").strip().lower()

    # Step 1: If args is a string, try JSON parsing
    if isinstance(args, str):
        cleaned_str = args.strip()
        if (cleaned_str.startswith("{") and cleaned_str.endswith("}")) or (cleaned_str.startswith("[") and cleaned_str.endswith("]")):
            try:
                parsed = json.loads(cleaned_str)
                return unwrap_tool_args(parsed, tool_name=clean_tool)
            except Exception:
                pass
        # Raw non-JSON string for a tool
        if clean_tool == "calculator":
            if cleaned_str.lower().startswith("expression:"):
                cleaned_str = cleaned_str[11:].strip()
            return {"expression": cleaned_str}
        elif clean_tool == "read_file":
            if cleaned_str.lower().startswith("filename:"):
                cleaned_str = cleaned_str[9:].strip()
            elif cleaned_str.lower().startswith("file_path:"):
                cleaned_str = cleaned_str[10:].strip()
            return {"filename": cleaned_str}
        elif clean_tool in ("search_documents", "read_sql"):
            if cleaned_str.lower().startswith("query:"):
                cleaned_str = cleaned_str[6:].strip()
            return {"query": cleaned_str}
        return {"query": cleaned_str}

    if not isinstance(args, dict):
        return {}

    current = dict(args)

    # Unwrap if current contains wrapper keys
    max_depth = 5
    for _ in range(max_depth):
        if not isinstance(current, dict):
            break

        # Check if single key is a wrapper key
        if len(current) == 1:
            k = next(iter(current.keys()))
            norm_k = clean_wrapper_key(k)
            if norm_k in WRAPPER_KEYS:
                val = current[k]
                if isinstance(val, str):
                    try:
                        parsed_val = json.loads(val.strip())
                        if isinstance(parsed_val, dict):
                            current = parsed_val
                            continue
                        elif isinstance(parsed_val, (int, float, bool)):
                            val = str(parsed_val)
                    except Exception:
                        pass
                    clean_val = str(val).strip()
                    if clean_tool == "calculator":
                        if clean_val.lower().startswith("expression:"):
                            clean_val = clean_val[11:].strip()
                        return {"expression": clean_val}
                    elif clean_tool == "read_file":
                        if clean_val.lower().startswith("filename:"):
                            clean_val = clean_val[9:].strip()
                        elif clean_val.lower().startswith("file_path:"):
                            clean_val = clean_val[10:].strip()
                        return {"filename": clean_val}
                    else:
                        if clean_val.lower().startswith("query:"):
                            clean_val = clean_val[6:].strip()
                        return {"query": clean_val}
                elif isinstance(val, dict):
                    current = val
                    continue
                else:
                    return {}
            else:
                break
        else:
            # Check if there are metadata keys like action, tool, thought alongside a single wrapper key
            wrapper_candidates = [
                k for k in current.keys()
                if clean_wrapper_key(k) in WRAPPER_KEYS
            ]
            non_wrapper = [
                k for k in current.keys()
                if k not in wrapper_candidates
            ]
            if len(wrapper_candidates) == 1 and all(k.strip().lower() in ("action", "tool", "name", "thought") for k in non_wrapper):
                val = current[wrapper_candidates[0]]
                if isinstance(val, str):
                    try:
                        parsed_val = json.loads(val.strip())
                        if isinstance(parsed_val, dict):
                            current = parsed_val
                            continue
                    except Exception:
                        pass
                    clean_val = str(val).strip()
                    if clean_tool == "calculator":
                        if clean_val.lower().startswith("expression:"):
                            clean_val = clean_val[11:].strip()
                        return {"expression": clean_val}
                    elif clean_tool == "read_file":
                        if clean_val.lower().startswith("filename:"):
                            clean_val = clean_val[9:].strip()
                        elif clean_val.lower().startswith("file_path:"):
                            clean_val = clean_val[10:].strip()
                        return {"filename": clean_val}
                    else:
                        if clean_val.lower().startswith("query:"):
                            clean_val = clean_val[6:].strip()
                        return {"query": clean_val}
                elif isinstance(val, dict):
                    current = val
                    continue
            break

    return current


def normalize_tool_args(tool_name: str, args: Any) -> Dict[str, Any]:
    """
    Unwraps and normalizes tool arguments to guarantee matching signature for tool functions.
    Never passes wrapper keys like 'args', 'parameters', etc. to the underlying tool function.
    """
    clean_tool = (tool_name or "").strip().lower()
    unwrapped = unwrap_tool_args(args, tool_name=clean_tool)

    if not isinstance(unwrapped, dict):
        unwrapped = {}
    else:
        unwrapped = dict(unwrapped)

    # Normalize tool parameter names
    if clean_tool == "search_documents":
        if "query" not in unwrapped:
            for alt in ["question", "text", "search", "expression", "prompt", "input", "query:"]:
                if alt in unwrapped:
                    val = unwrapped.pop(alt)
                    if isinstance(val, dict):
                        sub = normalize_tool_args(clean_tool, val)
                        if "query" in sub:
                            unwrapped["query"] = sub["query"]
                            break
                    unwrapped["query"] = str(val)
                    break
        # If any wrapper key still lingers, unwrap it
        for wk in list(unwrapped.keys()):
            if clean_wrapper_key(wk) in WRAPPER_KEYS and wk != "query":
                nested = unwrapped.pop(wk)
                if isinstance(nested, dict):
                    for nk, nv in nested.items():
                        if nk not in unwrapped:
                            unwrapped[nk] = nv
                elif isinstance(nested, str) and "query" not in unwrapped:
                    clean_nested = nested.strip()
                    if clean_nested.lower().startswith("query:"):
                        clean_nested = clean_nested[6:].strip()
                    unwrapped["query"] = clean_nested
        if "query" in unwrapped and isinstance(unwrapped["query"], str):
            if unwrapped["query"].strip().lower().startswith("query:"):
                unwrapped["query"] = unwrapped["query"].strip()[6:].strip()

    elif clean_tool == "calculator":
        if "expression" not in unwrapped:
            for alt in ["query", "input", "calc", "math", "question", "expr", "expression:"]:
                if alt in unwrapped:
                    val = unwrapped.pop(alt)
                    if isinstance(val, dict):
                        sub = normalize_tool_args(clean_tool, val)
                        if "expression" in sub:
                            unwrapped["expression"] = sub["expression"]
                            break
                    unwrapped["expression"] = str(val)
                    break
        for wk in list(unwrapped.keys()):
            if clean_wrapper_key(wk) in WRAPPER_KEYS and wk != "expression":
                nested = unwrapped.pop(wk)
                if isinstance(nested, dict):
                    for nk, nv in nested.items():
                        if nk not in unwrapped:
                            unwrapped[nk] = nv
                elif isinstance(nested, str) and "expression" not in unwrapped:
                    clean_nested = nested.strip()
                    if clean_nested.lower().startswith("expression:"):
                        clean_nested = clean_nested[11:].strip()
                    unwrapped["expression"] = clean_nested
        if "expression" in unwrapped and isinstance(unwrapped["expression"], str):
            if unwrapped["expression"].strip().lower().startswith("expression:"):
                unwrapped["expression"] = unwrapped["expression"].strip()[11:].strip()

    elif clean_tool == "read_sql":
        if "query" not in unwrapped:
            for alt in ["sql", "statement", "command", "expression", "input", "query:"]:
                if alt in unwrapped:
                    val = unwrapped.pop(alt)
                    if isinstance(val, dict):
                        sub = normalize_tool_args(clean_tool, val)
                        if "query" in sub:
                            unwrapped["query"] = sub["query"]
                            break
                    unwrapped["query"] = str(val)
                    break
        for wk in list(unwrapped.keys()):
            if clean_wrapper_key(wk) in WRAPPER_KEYS and wk != "query":
                nested = unwrapped.pop(wk)
                if isinstance(nested, dict):
                    for nk, nv in nested.items():
                        if nk not in unwrapped:
                            unwrapped[nk] = nv
                elif isinstance(nested, str) and "query" not in unwrapped:
                    clean_nested = nested.strip()
                    if clean_nested.lower().startswith("query:"):
                        clean_nested = clean_nested[6:].strip()
                    unwrapped["query"] = clean_nested
        if "query" in unwrapped and isinstance(unwrapped["query"], str):
            if unwrapped["query"].strip().lower().startswith("query:"):
                unwrapped["query"] = unwrapped["query"].strip()[6:].strip()

    elif clean_tool == "read_file":
        if "filename" not in unwrapped:
            for alt in ["file_path", "path", "filename", "file", "target", "input", "filename:", "file_path:"]:
                if alt in unwrapped:
                    val = unwrapped.pop(alt)
                    if isinstance(val, dict):
                        sub = normalize_tool_args(clean_tool, val)
                        if "filename" in sub:
                            unwrapped["filename"] = sub["filename"]
                            break
                    unwrapped["filename"] = str(val)
                    break
        for wk in list(unwrapped.keys()):
            if clean_wrapper_key(wk) in WRAPPER_KEYS and wk != "filename":
                nested = unwrapped.pop(wk)
                if isinstance(nested, dict):
                    for nk, nv in nested.items():
                        if nk not in unwrapped:
                            unwrapped[nk] = nv
                elif isinstance(nested, str) and "filename" not in unwrapped:
                    clean_nested = nested.strip()
                    if clean_nested.lower().startswith("filename:"):
                        clean_nested = clean_nested[9:].strip()
                    elif clean_nested.lower().startswith("file_path:"):
                        clean_nested = clean_nested[10:].strip()
                    unwrapped["filename"] = clean_nested
        if "filename" in unwrapped and isinstance(unwrapped["filename"], str):
            if unwrapped["filename"].strip().lower().startswith("filename:"):
                unwrapped["filename"] = unwrapped["filename"].strip()[9:].strip()
            elif unwrapped["filename"].strip().lower().startswith("file_path:"):
                unwrapped["filename"] = unwrapped["filename"].strip()[10:].strip()

    return unwrapped


def validate_agent_action(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Validates that the parsed JSON strictly conforms to the agent protocol:
    Either {"action": "tool", "tool": "<name>", "args": {...}}
    Or     {"action": "final", "answer": "<text>"}
    Forgiving for small model variations (e.g. putting tool name in action or wrapping args).
    """
    if "function" in data and isinstance(data["function"], dict):
        data = dict(data["function"])
    elif "tool_call" in data and isinstance(data["tool_call"], dict):
        data = dict(data["tool_call"])

    action = data.get("action")
    if not action:
        if data.get("tool") or data.get("name"):
            action = "tool"
        elif data.get("answer") is not None:
            action = "final"
        else:
            from backend.tools import tool_registry
            for k in data.keys():
                if tool_registry.get(k.lower().strip()) is not None:
                    action = k.lower().strip()
                    break
            if not action:
                raise ValueError("Missing 'action' field in JSON. Must be 'tool' or 'final'.")

    action = str(action).lower().strip()
    if action == "tool":
        tool_name = data.get("tool") or data.get("name")
        if not tool_name or not isinstance(tool_name, str):
            raise ValueError("Tool action must specify a 'tool' string name.")

        raw_args = None
        for k in data.keys():
            if clean_wrapper_key(k) in WRAPPER_KEYS:
                raw_args = data[k]
                break

        if raw_args is None:
            reserved = {"action", "tool", "name", "thought"}
            fallback_args = {k: v for k, v in data.items() if k.lower().strip() not in reserved and clean_wrapper_key(k) not in WRAPPER_KEYS}
            raw_args = fallback_args if fallback_args else {}

        normalized_args = normalize_tool_args(tool_name.strip(), raw_args)
        return "tool", {"tool": tool_name.strip(), "args": normalized_args}

    elif action == "final":
        answer = data.get("answer")
        if answer is None:
            raise ValueError("Final action must include an 'answer' field.")
        return "final", {"answer": str(answer)}

    else:
        # Check if small model wrote tool name directly as the action (e.g. {"action": "calculator", ...})
        from backend.tools import tool_registry
        if tool_registry.get(action) is not None:
            tool_name = action
            raw_args = None
            for k in data.keys():
                if clean_wrapper_key(k) in WRAPPER_KEYS:
                    raw_args = data[k]
                    break

            if raw_args is None:
                reserved = {"action", "tool", "name", "thought"}
                fallback_args = {k: v for k, v in data.items() if k.lower().strip() not in reserved and clean_wrapper_key(k) not in WRAPPER_KEYS}
                raw_args = fallback_args if fallback_args else {}

            normalized_args = normalize_tool_args(tool_name.strip(), raw_args)
            return "tool", {"tool": tool_name.strip(), "args": normalized_args}

        raise ValueError(f"Unrecognized action '{action}'. Must be 'tool' or 'final'.")


def build_system_prompt(agent: Agent, allowed_tools_info: List[Dict[str, Any]]) -> str:
    """Builds the comprehensive system prompt instructing the model on available tools and JSON schema."""
    tools_formatted = []
    for t in allowed_tools_info:
        tools_formatted.append(
            f"- Tool: `{t['name']}` (Risk: {t['risk_level']})\n"
            f"  Description: {t['description']}\n"
            f"  Parameters Schema: {json.dumps(t['parameters'])}"
        )

    tools_section = "\n\n".join(tools_formatted) if tools_formatted else "None."

    prompt = f"""{agent.system_prompt}

You are an autonomous offline agent running on an on-premise sovereign system.
You can call tools to find information or compute answers.

### AVAILABLE TOOLS (Allowed For You Only):
{tools_section}

### STRICT OPERATING RULES:
1. You must reply ONLY with a single valid JSON object.
2. Do not write introductory words, explanations, markdown outside the JSON, or conversational filler.
3. Your reply MUST adhere to one of these two exact schemas:

Schema A (To invoke a tool):
{{
  "action": "tool",
  "tool": "<tool_name>",
  "args": {{ ... }}
}}

Schema B (When you have enough information to answer the user):
{{
  "action": "final",
  "answer": "<complete answer, with source citations if retrieved from documents>"
}}

4. Always cite sources (filename and chunk number) if your answer is based on search_documents.
5. If a tool returns an error or observation, analyze it and decide your next action.
6. If the knowledge base or documents do not contain the answer, or if search_documents returns no relevant results, reply with Schema B stating clearly: "I do not know." or "The provided documents do not contain this information."
7. For ANY math, percentage, or calculation question, if the `calculator` tool is available to you, you MUST invoke the `calculator` tool first using Schema A. Never perform mental math or calculate answers in your head.
"""
    if getattr(settings, "PROMPT_VARIANT", "hardened").lower() != "baseline":
        prompt += """8. For ANY question asking about database records, students, departments, marks, or tables, if the `read_sql` tool is available to you, you MUST invoke `read_sql` first using Schema A. Do NOT write hypothetical SQL queries in the final answer without executing them.
9. For ANY factual question about documents, specifications, architecture, system parameters, or deployment, if the `search_documents` tool is available to you, you MUST invoke `search_documents` first using Schema A.
"""
    has_sql = any(t["name"] == "read_sql" for t in allowed_tools_info)
    if has_sql:
        from backend.tools import get_demo_db_schema
        schema_info = get_demo_db_schema()
        prompt += f"""
### DEMO DATABASE SCHEMA (SQLite):
The demo database is SQLite. Do NOT query MySQL information_schema or execute SHOW TABLES.
Only run valid SQLite SELECT queries against the following actual tables and columns:
{schema_info}
"""
    return prompt



def record_step(
    db: Session,
    run_id: int,
    step_number: int,
    step_type: str,
    input_data: Any,
    output_data: Any,
    latency_ms: float = 0.0,
) -> Step:
    """Helper to persist a step trace in the database with PII masked."""
    from backend.policy import mask_pii

    in_str = input_data if isinstance(input_data, str) else json.dumps(input_data)
    out_str = output_data if isinstance(output_data, str) else json.dumps(output_data)

    safe_in = mask_pii(in_str)
    safe_out = mask_pii(out_str)

    step = Step(
        run_id=run_id,
        step_number=step_number,
        step_type=step_type,
        input_data=safe_in,
        output_data=safe_out,
        latency_ms=round(latency_ms, 2),
        created_at=datetime.utcnow(),
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


class AgentRunner:
    """Executes the agent loop with memory, policy, and trace logging."""

    @staticmethod
    def run_agent(
        run_id: int,
        db: Session,
        max_iterations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Runs or resumes an agent workflow.
        Guarantees that run.status never stays in 'running' if an unexpected exception occurs.
        """
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise ValueError(f"Run {run_id} not found.")

        start_time = time.time()
        try:
            return AgentRunner._execute_agent_loop(
                run=run,
                db=db,
                start_time=start_time,
                max_iterations=max_iterations,
            )
        except Exception as exc:
            run.status = "failed"
            run.final_answer = f"Agent execution aborted due to unexpected error: {str(exc)}"
            run.total_latency_ms = (time.time() - start_time) * 1000
            try:
                db.commit()
            except Exception:
                db.rollback()
            return {
                "status": "failed",
                "answer": run.final_answer,
                "run_id": run.id,
            }

    @staticmethod
    def _execute_agent_loop(
        run: Run,
        db: Session,
        start_time: float,
        max_iterations: Optional[int] = None,
    ) -> Dict[str, Any]:
        run_id = run.id
        agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
        user = db.query(User).filter(User.id == run.user_id).first()
        max_iters = max_iterations or settings.MAX_AGENT_ITERATIONS

        # Fetch allowed tool definitions
        allowed_tool_names = agent.get_allowed_tools_list()
        allowed_tools_info = [
            tool_registry.get(name).to_definition().model_dump()
            for name in allowed_tool_names
            if tool_registry.get(name) is not None
        ]

        system_instruction = build_system_prompt(agent, allowed_tools_info)

        # Build message history from existing steps (to support resuming after approval)
        existing_steps = (
            db.query(Step)
            .filter(Step.run_id == run_id)
            .order_by(Step.step_number)
            .all()
        )

        step_counter = len(existing_steps)

        # Reconstruct conversation context
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": f"User Question: {run.question}"},
        ]

        sources_used = []
        had_tool_error = any(st.step_type == "tool" and "Tool Execution Error" in (st.output_data or "") for st in existing_steps)
        had_retry = any(st.step_type == "retry" for st in existing_steps)

        prior_latency = run.total_latency_ms or 0.0
        failed_call_signatures = set()

        # Replay completed steps into messages and detect previous tool failures
        for st in existing_steps:
            if st.step_type == "llm":
                messages.append({"role": "assistant", "content": st.output_data})
            elif st.step_type == "tool":
                messages.append(
                    {"role": "user", "content": f"Tool Observation ({st.input_data}):\n{st.output_data}"}
                )
                if ("Source:" in (st.output_data or "") or "search_documents" in (st.input_data or "")) and not (st.output_data or "").startswith("Tool Execution Error"):
                    sources_used.append(st.output_data)
                if "Error" in (st.output_data or ""):
                    failed_call_signatures.add(st.input_data)
            elif st.step_type == "policy":
                if "denied" in (st.output_data or "").lower() or "blocked" in (st.output_data or "").lower():
                    failed_call_signatures.add(st.input_data)

        # Check if there was an approval recently decided that needs execution
        pending_approval = (
            db.query(Approval)
            .filter(Approval.run_id == run_id, Approval.status.in_(["approved", "denied"]))
            .order_by(Approval.id.desc())
            .first()
        )

        # If run was paused and approval was just granted, execute the approved tool
        if run.status == "paused_for_approval" and pending_approval:
            if pending_approval.status == "approved":
                step_counter += 1
                t_start = time.time()
                tool_name = pending_approval.tool_name
                tool_args = json.loads(pending_approval.tool_args)
                tool = tool_registry.get(tool_name)

                try:
                    tool_output = str(tool.func(**tool_args))
                except Exception as e:
                    tool_output = f"Tool execution failed: {str(e)}"
                    failed_call_signatures.add((tool_name, json.dumps(tool_args, sort_keys=True)))

                if "Error" in tool_output:
                    failed_call_signatures.add((tool_name, json.dumps(tool_args, sort_keys=True)))

                t_lat = (time.time() - t_start) * 1000
                record_step(
                    db=db,
                    run_id=run_id,
                    step_number=step_counter,
                    step_type="tool",
                    input_data=f"{tool_name}({json.dumps(tool_args)})",
                    output_data=tool_output,
                    latency_ms=t_lat,
                )
                messages.append({
                    "role": "user",
                    "content": f"Tool Observation ({tool_name}):\n{tool_output}"
                })
                run.status = "running"
                db.commit()

            elif pending_approval.status == "denied":
                step_counter += 1
                tool_name = pending_approval.tool_name
                try:
                    denied_args = json.loads(pending_approval.tool_args)
                    failed_call_signatures.add((tool_name, json.dumps(denied_args, sort_keys=True)))
                except Exception:
                    pass

                record_step(
                    db=db,
                    run_id=run_id,
                    step_number=step_counter,
                    step_type="policy",
                    input_data=f"Denied approval for {pending_approval.tool_name}",
                    output_data="Human supervisor denied this high-risk action.",
                    latency_ms=0.0,
                )
                messages.append({
                    "role": "user",
                    "content": f"Observation: High-risk action '{pending_approval.tool_name}' was DENIED by the supervisor. Proceed without it."
                })
                run.status = "running"
                db.commit()

        # Update run status to running
        run.status = "running"
        db.commit()

        iteration = 0
        while iteration < max_iters:
            iteration += 1
            step_counter += 1

            # Step 1: Call LLM
            llm_start = time.time()
            chat_format = "json" if getattr(settings, "OLLAMA_JSON_MODE", True) else None
            try:
                llm_response = ollama_client.chat(
                    messages=messages,
                    model=agent.model,
                    temperature=agent.temperature,
                    format=chat_format,
                )
            except OllamaError as oe:
                llm_latency = (time.time() - llm_start) * 1000
                record_step(
                    db=db,
                    run_id=run_id,
                    step_number=step_counter,
                    step_type="llm",
                    input_data="[Ollama Chat Call]",
                    output_data=f"LLM Error: {str(oe)}",
                    latency_ms=llm_latency,
                )
                run.status = "failed"
                run.final_answer = f"Error during model communication: {str(oe)}"
                run.total_latency_ms = (time.time() - start_time) * 1000
                db.commit()
                return {
                    "status": "failed",
                    "answer": run.final_answer,
                    "run_id": run.id,
                }

            llm_latency = (time.time() - llm_start) * 1000
            record_step(
                db=db,
                run_id=run_id,
                step_number=step_counter,
                step_type="llm",
                input_data=f"Prompt context ({len(messages)} messages)",
                output_data=llm_response,
                latency_ms=llm_latency,
            )
            messages.append({"role": "assistant", "content": llm_response})

            # Step 2: Parse and validate JSON (with retries if enabled)
            action_type = None
            action_data = None
            retry_count = 0
            max_retries = 2 if settings.ENABLE_RETRY else 0

            parse_error = None
            try:
                raw_json = extract_json_from_llm(llm_response)
                action_type, action_data = validate_agent_action(raw_json)
            except Exception as e:
                parse_error = str(e)

            while parse_error and retry_count < max_retries:
                had_retry = True
                retry_count += 1
                step_counter += 1
                retry_start = time.time()

                corrective_prompt = (
                    f"Error: {parse_error}. Reply with valid JSON only conforming to Schema A or Schema B."
                )
                messages.append({"role": "user", "content": corrective_prompt})

                try:
                    retry_response = ollama_client.chat(
                        messages=messages,
                        model=agent.model,
                        temperature=0.1,  # Lower temperature for formatting correction
                        format=chat_format,
                    )

                except Exception as oe:
                    retry_response = f"Retry connection error: {oe}"

                retry_lat = (time.time() - retry_start) * 1000
                record_step(
                    db=db,
                    run_id=run_id,
                    step_number=step_counter,
                    step_type="retry",
                    input_data=f"Retry {retry_count}: {corrective_prompt}",
                    output_data=retry_response,
                    latency_ms=retry_lat,
                )
                messages.append({"role": "assistant", "content": retry_response})

                try:
                    raw_json = extract_json_from_llm(retry_response)
                    action_type, action_data = validate_agent_action(raw_json)
                    parse_error = None  # Successfully resolved
                except Exception as e:
                    parse_error = str(e)

            if parse_error:
                # If still invalid after retries, fail run
                run.status = "failed"
                run.final_answer = (
                    f"Model output format failure after retries: {parse_error}. "
                    f"Raw response: {llm_response[:300]}"
                )
                run.total_latency_ms = (time.time() - start_time) * 1000
                db.commit()
                return {
                    "status": "failed",
                    "answer": run.final_answer,
                    "run_id": run.id,
                }

            # Step 3: Handle Final Action
            if action_type == "final":
                final_answer = action_data["answer"]

                # Optional Post-hoc Constraint: Document Assistant must perform retrieval before abstaining
                if getattr(settings, "REQUIRE_RETRIEVAL_BEFORE_ABSTAIN", False) and agent.name == "Document Assistant":
                    from eval.metrics import is_abstention
                    if is_abstention(final_answer):
                        search_succeeded = any(
                            st.step_type == "tool" and "search_documents" in st.input_data and not st.output_data.startswith("Tool Execution Error")
                            for st in db.query(Step).filter(Step.run_id == run_id).all()
                        )
                        if not search_succeeded and not getattr(run, "_abstention_nudged", False):
                            run._abstention_nudged = True
                            step_counter += 1
                            record_step(
                                db=db,
                                run_id=run_id,
                                step_number=step_counter,
                                step_type="policy",
                                input_data="Policy check: REQUIRE_RETRIEVAL_BEFORE_ABSTAIN",
                                output_data="Document Assistant attempted to abstain without successful retrieval. Prompting retrieval.",
                                latency_ms=0.0,
                            )
                            messages.append({
                                "role": "user",
                                "content": "You must invoke search_documents with an appropriate search query before concluding that information is absent.",
                            })
                            continue

                run.status = "completed"
                run.final_answer = final_answer
                run.total_latency_ms = prior_latency + ((time.time() - start_time) * 1000)
                db.commit()
                return {
                    "status": "completed",
                    "answer": final_answer,
                    "sources": sources_used,
                    "run_id": run.id,
                    "recovered_tool_error": had_tool_error or had_retry,
                }

            # Step 4: Handle Tool Action
            elif action_type == "tool":
                tool_name = action_data["tool"]
                tool_args = normalize_tool_args(tool_name, action_data.get("args", {}))

                current_call_signature = (tool_name, json.dumps(tool_args, sort_keys=True))
                sig_str = f"{tool_name}({json.dumps(tool_args)})"
                is_failed_repeat = (current_call_signature in failed_call_signatures) or (sig_str in failed_call_signatures)
                is_immediate_repeat = getattr(run, "_last_tool_call", None) == current_call_signature

                # Guard against repeated identical tool calls causing loop thrashing or re-triggering approvals
                if is_failed_repeat or is_immediate_repeat:
                    step_counter += 1
                    record_step(
                        db=db,
                        run_id=run_id,
                        step_number=step_counter,
                        step_type="policy",
                        input_data=f"Blocked duplicate tool call: {tool_name}",
                        output_data=f"Tool '{tool_name}' with identical arguments already failed, was denied, or was executed. Repeated invocation blocked.",
                        latency_ms=0.0,
                    )
                    messages.append({
                        "role": "user",
                        "content": f"Loop Warning: Tool '{tool_name}' with arguments {json.dumps(tool_args)} has already been attempted in this run. Do not repeat the identical call. Formulate your final answer using available information or choose a different action.",
                    })
                    continue
                run._last_tool_call = current_call_signature

                step_counter += 1
                # Evaluate Policy Layer
                policy_start = time.time()
                decision, reason, approval_id = evaluate_policy(
                    tool_name=tool_name,
                    agent_allowed_tools=allowed_tool_names,
                    user_role=user.role,
                    username=user.username,
                    run_id=run.id,
                    tool_args=tool_args,
                    db=db,
                )
                policy_lat = (time.time() - policy_start) * 1000

                record_step(
                    db=db,
                    run_id=run_id,
                    step_number=step_counter,
                    step_type="policy",
                    input_data=f"Policy check: {tool_name}",
                    output_data=f"Decision: {decision}. Reason: {reason}",
                    latency_ms=policy_lat,
                )

                if decision == PolicyDecision.REQUIRES_APPROVAL:
                    run.status = "paused_for_approval"
                    run.total_latency_ms = prior_latency + ((time.time() - start_time) * 1000)
                    db.commit()
                    return {
                        "status": "paused_for_approval",
                        "approval_id": approval_id,
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "message": f"Execution paused. Action '{tool_name}' requires human approval.",
                        "run_id": run.id,
                    }

                elif decision == PolicyDecision.DENIED:
                    failed_call_signatures.add(current_call_signature)
                    failed_call_signatures.add(sig_str)
                    # Inform agent of policy denial so it can adapt or answer
                    messages.append({
                        "role": "user",
                        "content": f"Policy Enforcement Notice: Tool '{tool_name}' execution was denied ({reason}). Choose a permitted tool or finalize.",
                    })
                    continue

                elif decision == PolicyDecision.ALLOWED:
                    # Execute the tool
                    step_counter += 1
                    t_exec_start = time.time()
                    tool_obj = tool_registry.get(tool_name)
                    tool_args = normalize_tool_args(tool_name, tool_args)
                    try:
                        tool_result = str(tool_obj.func(**tool_args))
                    except Exception as e:
                        tool_result = f"Tool Execution Error: {str(e)}"
                        had_tool_error = True
                        failed_call_signatures.add(current_call_signature)
                        failed_call_signatures.add(sig_str)

                    if "Error" in tool_result:
                        failed_call_signatures.add(current_call_signature)
                        failed_call_signatures.add(sig_str)

                    t_exec_lat = (time.time() - t_exec_start) * 1000
                    record_step(
                        db=db,
                        run_id=run_id,
                        step_number=step_counter,
                        step_type="tool",
                        input_data=f"{tool_name}({json.dumps(tool_args)})",
                        output_data=tool_result,
                        latency_ms=t_exec_lat,
                    )

                    if ("Source:" in tool_result or tool_name == "search_documents") and not tool_result.startswith("Tool Execution Error"):
                        sources_used.append(tool_result)

                    messages.append({
                        "role": "user",
                        "content": f"Tool Observation ({tool_name}):\n{tool_result}",
                    })
                    continue

        # If max iterations exhausted
        run.status = "completed"
        fallback_msg = (
            "Maximum reasoning iterations reached. Partial context gathered. "
            "Please review the trace steps for detailed observations."
        )
        run.final_answer = fallback_msg
        run.total_latency_ms = prior_latency + ((time.time() - start_time) * 1000)
        db.commit()
        return {
            "status": "completed",
            "answer": fallback_msg,
            "sources": sources_used,
            "run_id": run.id,
            "recovered_tool_error": had_tool_error or had_retry,
        }
