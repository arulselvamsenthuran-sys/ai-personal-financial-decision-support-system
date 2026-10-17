"""Security audit logging module.

Records security-relevant events without logging sensitive data (passwords, tokens, credentials).
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional
import uuid

logger = logging.getLogger("security.audit")


def audit_log(
    event_type: str,
    user_id: Optional[uuid.UUID] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[Any] = None,
    status: str = "SUCCESS",
    ip_address: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a security audit log event.

    Args:
        event_type: Category of security event (e.g. LOGIN_SUCCESS, LOGIN_FAILURE, ACCESS_DENIED)
        user_id: ID of the acting user if authenticated
        resource_type: Type of resource accessed/modified (e.g. FINANCIAL_ACCOUNT)
        resource_id: ID of resource accessed/modified
        status: SUCCESS, FAILURE, or BLOCKED
        ip_address: Client IP address
        details: Additional safe key-value metadata (NEVER include secrets)
    """
    safe_details = details.copy() if details else {}
    
    # Strip any potential sensitive keys if accidentally passed
    sensitive_keys = {"password", "token", "password_hash", "session_token_hash", "secret", "credit_card"}
    for key in list(safe_details.keys()):
        if any(s in key.lower() for s in sensitive_keys):
            safe_details[key] = "[REDACTED]"

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "user_id": str(user_id) if user_id else None,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "status": status,
        "ip_address": ip_address,
        "details": safe_details,
    }

    logger.info(
        "AUDIT_EVENT: %s",
        event,
        extra={"event": f"audit.{event_type.lower()}"},
    )
