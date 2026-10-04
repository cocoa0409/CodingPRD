"""Authentication (priority 1) and role authorization (priority 3)."""
from flask import request

from constants import ROLES
from errors import ApiError


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be declared",
            401,
        )
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "role %s is not authorized for this endpoint" % role,
            403,
        )
