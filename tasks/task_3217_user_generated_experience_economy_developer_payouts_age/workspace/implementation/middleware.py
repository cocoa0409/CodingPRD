"""Auth middleware per PRD §2.1 and validations priority 1-2."""
from flask import request

from errors import (
    err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
)

ROLES = {
    "Anonymous",
    "Creator",
    "Moderator",
    "AppealsReviewer",
    "SafetyAgent",
    "FinanceOfficer",
    "PlatformAdmin",
}


def auth_context():
    """Extract and validate X-User-ID / X-User-Role headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID header missing or malformed",
        )
    if not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role header missing or malformed",
        )
    return user_id, role


def require_role(role, *allowed):
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED_ROLE, "Role not permitted for this operation")
