"""Header authentication and endpoint role authorization.

Authentication precedes authorization; both precede request shape and the
existence of any referenced resource.
"""
import functools

from flask import g, request

from common import ApiError, LOCK


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    return value.strip()


def authenticate():
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if not user_id or not role:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Both X-User-ID and X-User-Role headers are required.",
        )
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*roles):
    """Decorator: authenticate, authorize against the endpoint's role list, and
    serialize the request against the in-memory store."""
    allowed = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role '%s' is not authorized for this endpoint." % g.role,
                )
            with LOCK:
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_user():
    return g.user_id


def acting_role():
    return g.role
