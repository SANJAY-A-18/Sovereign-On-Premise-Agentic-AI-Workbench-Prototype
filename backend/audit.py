"""
Audit logging helper for Sovereign Workbench.
Provides structured recording of events, actions, and security decisions.
Ensures PII is automatically masked in log details, and never logs passwords or secrets.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from backend.db import AuditLog, SessionLocal


def log_audit_event(
    user: str,
    action: str,
    outcome: str,
    details: Optional[str] = None,
    db: Optional[Session] = None,
) -> AuditLog:
    """
    Persist an audit log entry.
    Masks PII before writing. Uses provided DB session or creates a new one.
    """
    from backend.policy import mask_pii

    safe_details = mask_pii(details) if details else ""

    # Never log tokens or raw credentials
    if any(k in safe_details.lower() for k in ("bearer", "password", "token", "secret", "jwt")):
        safe_details = mask_pii(safe_details)
        if any(k in safe_details.lower() for k in ("password", "secret", "bearer ")):
            safe_details = "[REDACTED_CREDENTIALS]"

    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True

    try:
        log_entry = AuditLog(
            timestamp=datetime.utcnow(),
            user=user,
            action=action,
            details=safe_details,
            outcome=outcome,
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry
    finally:
        if should_close:
            db.close()
