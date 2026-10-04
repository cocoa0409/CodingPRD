"""Auth middleware (validation priorities 1 and 2).

Priority 1: X-User-ID and X-User-Role must both be present and the role must be
one of the nine declared roles -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
Priority 2: the role must be in the endpoint's role list ->
ERR_INSUFFICIENT_PERMISSIONS (403).
"""

from functools import wraps

from flask import g, request

from constants import ROLE_SET, ROLES
from errors import ApiError

ANY_ROLES = tuple(ROLES)


def require_roles(*allowed):
    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLE_SET:
                raise ApiError(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID and X-User-Role headers must both be present and "
                    "X-User-Role must be a declared role",
                    400,
                )
            if role not in allowed_set:
                raise ApiError(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    "Role not allowed for this endpoint",
                    403,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
