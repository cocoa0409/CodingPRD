"""Identity headers and RBAC (PRD 2.1, ladder steps 1-3)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = ("PlanSponsor", "Administrator", "ComplianceOfficer", "Regulator")
ALL_ROLES = ROLES


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_MISSING_IDENTITY_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def guard(*allowed_roles):
    """Decorator running ladder steps 1-3 before the handler body."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate(allowed_roles)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def actor():
    return g.user_id
