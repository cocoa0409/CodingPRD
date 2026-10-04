"""Auth middleware: X-User-ID / X-User-Role extraction and RBAC checks."""

from flask import request

from errors import ApiError, raise_error, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"PlatformAdmin", "StoreManager", "GeneralManager", "LineWorker", "MarketplaceChannel"}


def get_auth():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers must be present and role must be recognized")
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers and role permission. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"Role {role} is not permitted for this endpoint")
    return user_id, role
