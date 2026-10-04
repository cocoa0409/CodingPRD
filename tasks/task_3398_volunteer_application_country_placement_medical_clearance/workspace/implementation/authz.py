"""Authentication and authorization (validation priorities 1-3).

Headers: X-User-ID + X-User-Role (PRD 2.1). Priority order:
  1. headers present and role declared      -> ERR_UNAUTHENTICATED 401
  2. acting role in endpoint's allowed set  -> ERR_FORBIDDEN 403
  3. applicant ownership (X-User-ID == application's applicant_id)
                                            -> ERR_NOT_OWNER 403
"""
from flask import request

from db import ROLES
from errors import err


def auth():
    """Validate the two mandatory headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401,
            "Missing or malformed X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role %s is not permitted for this operation" % role)


def require_owner(user_id, owner_id):
    if user_id != owner_id:
        err("ERR_NOT_OWNER", 403, "X-User-ID does not own the target resource")
