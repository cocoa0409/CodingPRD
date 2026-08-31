"""Auth header extraction and RBAC (PRD 2.1, validations priority 1-2)."""
from flask import request

from errors import err
from store import ROLES


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED")
    return user_id, role
