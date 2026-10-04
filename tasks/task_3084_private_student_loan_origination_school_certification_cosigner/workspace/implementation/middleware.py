"""Authentication and authorization (PRD 2.1 / 2.4, SCAFFOLD 1.4 priorities 1-2)."""

from functools import wraps

from flask import request

from errors import fail
from common import ROLES


def authenticate():
    """Both headers must be present and X-User-Role must name a declared role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    return user_id, role


def guard(*roles):
    """Decorator: authenticates and enforces the endpoint's authorized roles."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                fail("ERR_FORBIDDEN", "role %s may not perform this operation" % role)
            kwargs["_user_id"] = user_id
            kwargs["_role"] = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_borrower_owns(user_id, borrower_id):
    if user_id != borrower_id:
        fail("ERR_FORBIDDEN", "acting borrower does not own this resource")


def require_cosigner_is(user_id, cosigner_id):
    if user_id != cosigner_id:
        fail("ERR_FORBIDDEN", "acting cosigner is not this record")


def require_school_is(user_id, school_id):
    if user_id != school_id:
        fail("ERR_FORBIDDEN", "acting school is not this record")