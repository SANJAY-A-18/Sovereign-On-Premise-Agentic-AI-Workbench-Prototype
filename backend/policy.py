"""
Policy layer for Sovereign Workbench.
Enforces security, governance, and RBAC before any tool executes:
1. Tool must be in agent's allowlist
2. User's role must be authorized for the tool
3. High-risk tools require human approval (pausing execution)
4. Masks PII (emails, Indian phone numbers, Aadhaar-like 12-digit numbers)
5. Audit-logs every decision
"""

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from backend.db import Approval
from backend.audit import log_audit_event
from backend.tools import tool_registry

# ==============================================================================
# PII Masking Regular Expressions
# ==============================================================================

# 1. 12-digit Aadhaar number: 4 digits, optional space/dash, 4 digits, optional space/dash, 4 digits
AADHAAR_REGEX = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")

# 2. Indian Phone: +91 or 91 or 0 prefix optional, followed by 10 digits starting with 6-9
# Using negative lookbehind/lookahead to prevent partial matching inside larger numbers
PHONE_REGEX = re.compile(
    r"(?<!\d)(?:\+91[\-\s]?|91[\-\s]?|0)?[6-9]\d{4}[\-\s]?\d{5}(?!\d)"
)

# 3. Standard Email
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# 4. JWT Tokens and Bearer headers
JWT_REGEX = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\b")
BEARER_REGEX = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_.]+\b")

# 5. Raw password occurrences in JSON or strings
PASSWORD_REGEX = re.compile(r'(?i)("?(?:password|token|secret)"?\s*[:=]\s*)"[^"]+"')


def mask_pii(text: Optional[str]) -> str:
    """
    Mask sensitive personally identifiable information (PII) and credentials in text.
    Masks 12-digit Aadhaar numbers, 10-digit Indian phone numbers, email addresses,
    JWT tokens, Bearer authorization tokens, and plaintext passwords.
    Aadhaar is masked before phone to prevent collision on digit counts.
    """
    if not text:
        return ""

    masked = str(text)
    # 1. Mask 12-digit Aadhaar first
    masked = AADHAAR_REGEX.sub("[AADHAAR_MASKED]", masked)
    # 2. Mask 10-digit Indian phone numbers
    masked = PHONE_REGEX.sub("[PHONE_MASKED]", masked)
    # 3. Mask Email addresses
    masked = EMAIL_REGEX.sub("[EMAIL_MASKED]", masked)
    # 4. Mask JWT tokens and Bearer headers
    masked = JWT_REGEX.sub("[JWT_MASKED]", masked)
    masked = BEARER_REGEX.sub("Bearer [TOKEN_MASKED]", masked)
    # 5. Mask passwords/secrets
    masked = PASSWORD_REGEX.sub(r'\1"[PASSWORD_MASKED]"', masked)

    return masked


# ==============================================================================
# Role-Based Tool Access Rules
# ==============================================================================

# Define which roles are allowed to invoke which tools
ROLE_TOOL_ALLOWLIST = {
    "admin": ["*"],  # Admin can run any registered tool
    "user": [
        "search_documents",
        "calculator",
        "read_file",
        "read_sql",  # User may run read_sql, but it will still trigger the high-risk approval step
    ],
}


class PolicyDecision:
    ALLOWED = "allowed"
    DENIED = "denied"
    REQUIRES_APPROVAL = "requires_approval"


def evaluate_policy(
    tool_name: str,
    agent_allowed_tools: List[str],
    user_role: str,
    username: str,
    run_id: int,
    tool_args: Dict[str, Any],
    db: Session,
) -> Tuple[str, str, Optional[int]]:
    """
    Evaluates policy in strict order:
    1. Tool is in agent's allowlist
    2. User's role may use the tool
    3. If tool is high risk, require human approval
    
    Returns:
        (status, reason, approval_id_or_none)
        status: "allowed" | "denied" | "requires_approval"
    """
    tool = tool_registry.get(tool_name)
    if not tool:
        reason = f"Tool '{tool_name}' is not registered in the system."
        log_audit_event(
            user=username,
            action=f"policy_check:{tool_name}",
            outcome=PolicyDecision.DENIED,
            details=f"Run {run_id}: {reason}",
            db=db,
        )
        return PolicyDecision.DENIED, reason, None

    # Check (a): Tool in agent's allowlist
    if tool_name not in agent_allowed_tools:
        reason = f"Security Policy Violation: Tool '{tool_name}' is not permitted for this agent."
        log_audit_event(
            user=username,
            action=f"policy_check:{tool_name}",
            outcome=PolicyDecision.DENIED,
            details=f"Run {run_id}: {reason}",
            db=db,
        )
        return PolicyDecision.DENIED, reason, None

    # Check (b): User role permission
    allowed_for_role = ROLE_TOOL_ALLOWLIST.get(user_role, [])
    if "*" not in allowed_for_role and tool_name not in allowed_for_role:
        reason = f"Role Access Violation: User role '{user_role}' is not authorized to execute tool '{tool_name}'."
        log_audit_event(
            user=username,
            action=f"policy_check:{tool_name}",
            outcome=PolicyDecision.DENIED,
            details=f"Run {run_id}: {reason}",
            db=db,
        )
        return PolicyDecision.DENIED, reason, None

    # Check (c): For read_sql, validate query statically before requesting human approval
    if tool_name == "read_sql":
        from backend.tools import validate_sql_query, get_demo_db_schema
        raw_query = tool_args.get("query", "")
        is_valid, validation_msg = validate_sql_query(raw_query)
        if not is_valid:
            schema_info = get_demo_db_schema()
            reason = f"{validation_msg} Real database schema:\n{schema_info}"
            log_audit_event(
                user=username,
                action=f"policy_check:{tool_name}",
                outcome=PolicyDecision.DENIED,
                details=f"Run {run_id}: Invalid read_sql rejected before approval: {validation_msg}",
                db=db,
            )
            return PolicyDecision.DENIED, reason, None

    # Check (d): High risk requires human approval
    if tool.risk_level == "high":
        # Create a pending approval record with masked tool_args
        masked_args_str = mask_pii(json.dumps(tool_args))
        approval = Approval(
            run_id=run_id,
            tool_name=tool_name,
            tool_args=masked_args_str,
            status="pending",
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)

        reason = (
            f"High-Risk Tool: Execution of '{tool_name}' requires human approval. "
            f"Approval request #{approval.id} created."
        )
        log_audit_event(
            user=username,
            action=f"policy_approval_request:{tool_name}",
            outcome=PolicyDecision.REQUIRES_APPROVAL,
            details=f"Run {run_id}: Approval #{approval.id} created with args {masked_args_str}",
            db=db,
        )
        return PolicyDecision.REQUIRES_APPROVAL, reason, approval.id

    # All checks passed
    log_audit_event(
        user=username,
        action=f"policy_check:{tool_name}",
        outcome=PolicyDecision.ALLOWED,
        details=f"Run {run_id}: Tool '{tool_name}' approved by policy engine.",
        db=db,
    )
    return PolicyDecision.ALLOWED, "Policy check passed.", None
