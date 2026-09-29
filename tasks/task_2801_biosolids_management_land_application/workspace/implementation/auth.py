"""Authentication and authorization (PRD section 2.1, priorities 1 and 2)."""

from functools import wraps

from flask import g, request

from errors import fail
from store import ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "Header X-User-ID is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "Header X-User-Role is required.")
    g.user_id = user_id
    g.role = role
    return user_id, role


def roles(*allowed):
    allowed_set = tuple(allowed)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in ROLES or g.role not in allowed_set:
                fail("ERR_UNAUTHORIZED", "Role %s is not authorized for this operation." % g.role)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id
