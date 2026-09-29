"""Authentication headers (ranks 1-2), role admission (rank 3) and operator scope (rank 4)."""

import functools

from flask import g, request

from constants import ROLES
from errors import ApiError


def read_identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role is None or not role.strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    return user_id, role


def endpoint(roles):
    """Bind the authentication ladder to a view function."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = read_identity()
            g.user_id = user_id
            g.role = role
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def is_operator_user():
    return getattr(g, "role", None) == "OperatorUser"


def scope_operator_id(operator_id):
    """Refuse an OperatorUser reaching outside its own operator tree."""
    if is_operator_user() and operator_id != g.user_id:
        raise ApiError("ERR_OPERATOR_SCOPE_VIOLATION")


def visible_operator_id():
    """The operator id a collection read must be narrowed to, or None."""
    if is_operator_user():
        return g.user_id
    return None
