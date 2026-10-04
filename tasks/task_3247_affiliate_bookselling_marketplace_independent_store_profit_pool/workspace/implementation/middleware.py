"""Auth header extraction and role checking."""
from flask import request

from errors import err_unauthenticated, err_unauthorized, err_forbidden_owner

ROLES = {
    "PlatformAdmin",
    "StoreManager",
    "Partner",
    "Customer",
    "CustomerService",
    "WholesalerOps",
    "FinanceOps",
}


def get_auth():
    """Returns (user_id, role). Raises 401 if role missing/unknown."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err_unauthenticated()
    user_id = request.headers.get("X-User-ID")
    return user_id, role


def require_roles(allowed):
    """Raises 403 if the role is not in allowed. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_unauthorized()
    return user_id, role


def require_action_role(role_for_action, action):
    """For action endpoints: check role mapped for the specific action."""
    allowed = role_for_action.get(action)
    if allowed is None:
        return None
    user_id, role = get_auth()
    if role not in allowed:
        raise err_unauthorized()
    return user_id, role


def require_owner(actual_owner_id):
    """Compare X-User-ID to the owning id; 403 on mismatch."""
    user_id, _ = get_auth()
    if actual_owner_id is None or user_id != actual_owner_id:
        raise err_forbidden_owner()
