"""Auth middleware: header extraction, role validation, ownership checks."""
from flask import request

from db import store
from errors import err

ROLES = {"Anonymous", "Subscriber", "Support", "DistributorOps", "PlatformAdmin"}


def get_auth():
    """Return (role, user_id). Raises ERR_UNAUTHENTICATED on missing/malformed."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not isinstance(role, str) or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header")
    if not user_id or not isinstance(user_id, str):
        err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header")
    return role, user_id


def require_roles(*allowed):
    """Check role authorization. Returns (role, user_id)."""
    role, user_id = get_auth()
    if role not in allowed:
        err("ERR_UNAUTHORIZED", "Role %s not permitted for this endpoint" % role)
    return role, user_id


def check_owner(account_id, role, user_id):
    """For Subscriber role, X-User-ID must equal the owning account id."""
    if role == "Subscriber" and user_id != account_id:
        err("ERR_FORBIDDEN_NOT_OWNER", "Subscriber does not own this resource")
