"""Auth context extraction and role authorization (PRD 2.1, families 1-2).

Every endpoint requires X-User-ID and X-User-Role; the role must be one of
the seven declared roles and must be listed for the endpoint. The decorator
injects _uid / _role kwargs into the wrapped view.
"""
from functools import wraps

from flask import request

import constants
from errors import ApiError


def current_identity():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in constants.ROLES:
        raise ApiError(
            "ERR_MISSING_USER_CONTEXT",
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    return uid, role


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = current_identity()
            if role not in roles:
                raise ApiError(
                    "ERR_FORBIDDEN_ROLE",
                    "role '%s' is not permitted to call this endpoint" % role,
                )
            kwargs["_uid"] = uid
            kwargs["_role"] = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
