"""Auth context (pipeline stage 1), role admission (stage 2), and the
ownership comparison helper (stage 6) from PRD sections 2.1 and 2.8.

X-User-ID / X-User-Role must be present and non-empty on every request.
For entity-backed roles (TPAAdministrator, ProviderRep, Veteran) X-User-ID
is the id of the acting entity; ownership compares the resource's FK to it.
"""
from functools import wraps

from flask import request

from errors import fail


def context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not uid.strip() or not role.strip():
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-ID and X-User-Role headers must be present and non-empty")
    return uid, role


def endpoint(roles):
    """Decorator: runs stages 1-2, then calls fn(user_id, role, *path_params)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = context()
            if role not in roles:
                fail("ERR_UNAUTHORIZED_ROLE",
                     "role %s is not authorized for this endpoint" % role)
            return fn(uid, role, *args, **kwargs)
        return wrapper
    return decorator


def require_owner(user_id, owner_fk_value, what):
    if user_id != owner_fk_value:
        fail("ERR_OWNERSHIP_MISMATCH",
             "caller does not own this %s" % what)
