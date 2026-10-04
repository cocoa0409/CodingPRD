"""Auth middleware: X-User-ID / X-User-Role validation and RBAC enforcement."""
from functools import wraps

from flask import request

from constants import ROLES
from errors import err


def current_user():
    return getattr(request, "_user_id", None), getattr(request, "_role", None)


def require_roles(*allowed):
    """Decorator: validate auth headers then enforce the role set."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not isinstance(uid, str) or not uid.strip():
                raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                          "X-User-ID header missing or malformed")
            if not role or role not in ROLES:
                raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                          "X-User-Role header missing or invalid")
            request._user_id = uid
            request._role = role
            if allowed and role not in allowed:
                raise err("ERR_UNAUTHORIZED_ROLE",
                          "Role %s not permitted for this endpoint" % role)
            return fn(*args, **kwargs)

        return wrapper

    return deco
