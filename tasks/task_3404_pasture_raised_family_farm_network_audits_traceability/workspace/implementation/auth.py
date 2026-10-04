"""Authentication and role authorization (PRD 2.1, validation priorities 1-2).

Every request carries X-User-ID and X-User-Role; the role must be one of the
six declared role names. Missing headers or an unknown role -> 401
ERR_UNAUTHENTICATED; a known role not listed on the endpoint -> 403
ERR_FORBIDDEN.
"""
from flask import request

import constants as C
from errors import ApiError


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in C.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def authorize(role, allowed_roles):
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "role %s is not permitted on this endpoint" % role)
