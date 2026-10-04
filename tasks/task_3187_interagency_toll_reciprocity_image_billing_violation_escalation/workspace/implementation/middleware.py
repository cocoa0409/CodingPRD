"""Auth middleware: X-User-ID / X-User-Role validation and RBAC."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

VALID_ROLES = {
    "SettlementOfficer",
    "AgencyOperations",
    "AccountHolder",
    "ViolationsOfficer",
    "PlateLookupAgent",
}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID header missing or malformed",
            400,
        )
    if not role or role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role header missing or malformed",
            400,
        )
    return user_id, role


def require_roles(allowed):
    """Raise 403 if the caller's role is not in allowed. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            f"Role {role} not permitted for this endpoint",
            403,
        )
    return user_id, role
