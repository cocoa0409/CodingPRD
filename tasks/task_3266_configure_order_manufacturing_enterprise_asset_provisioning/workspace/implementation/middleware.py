from flask import request
from errors import err_unauthenticated, err_forbidden, ApiError

VALID_ROLES = {"PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps"}


def get_auth():
    """Return (user_id, role) or raise 401."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or not isinstance(uid, str) or not isinstance(role, str):
        raise err_unauthenticated()
    if role not in VALID_ROLES:
        raise err_unauthenticated("Malformed X-User-Role")
    return uid, role


def require_roles(*roles):
    uid, role = get_auth()
    if role not in roles:
        raise err_forbidden()
    return uid, role


def require_ownership(account_id, uid, role):
    """For CustomerUser, X-User-ID must match the owning account id."""
    if role == "CustomerUser" and uid != account_id:
        raise err_forbidden("CustomerUser may only act on own account's resources")
