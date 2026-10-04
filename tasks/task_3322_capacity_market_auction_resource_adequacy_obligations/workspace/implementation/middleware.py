"""Auth middleware: X-User-ID / X-User-Role extraction and role checking."""
from flask import request

from errors import err_unauthenticated, err_forbidden

ROLES = ("MarketAdmin", "ResourceOwner", "SettlementOps")


def get_auth():
    """Validate auth headers. Returns (user_id, role). Raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES or not user_id or not user_id.strip():
        raise err_unauthenticated()
    return user_id.strip(), role


def require_roles(*allowed):
    """Validate auth and that the role is permitted. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_forbidden()
    return user_id, role


def require_any():
    """Any authenticated role."""
    return get_auth()
