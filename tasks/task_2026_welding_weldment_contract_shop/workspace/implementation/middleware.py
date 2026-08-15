"""Auth: X-User-ID / X-User-Role header extraction and role authorization."""

import functools

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from helpers import ALL_ROLES


def current_user():
    """Extract and validate the user-context headers (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or role is None
        or not isinstance(user_id, str)
        or not user_id.strip()
        or role not in ALL_ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID or X-User-Role header missing or invalid",
        )
    return user_id, role


def require_roles(*roles):
    """Decorator: enforce header presence then role authorization (priorities 1-2)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = current_user()
            if role not in roles:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    403,
                    "Role lacks permission for this operation",
                )
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return decorator


def require_any(fn):
    """GET endpoints: any authenticated role may read."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user_id, role = current_user()
        return fn(user_id, role, *args, **kwargs)

    return wrapper
