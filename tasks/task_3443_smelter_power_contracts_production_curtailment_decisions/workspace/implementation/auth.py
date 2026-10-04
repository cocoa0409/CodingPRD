"""Authentication and role-authorization middleware (PRD 2.1, 2.7 rules 1-2)."""
from functools import wraps

from flask import g, request

from constants import ROLES
from errors import raise_err


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            "ERR_UNAUTHENTICATED",
            "Missing X-User-ID / X-User-Role headers or undeclared role.",
        )
    return user_id, role


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                raise_err(
                    "ERR_UNAUTHORIZED",
                    "Role %s is not authorized for this endpoint." % role,
                )
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
