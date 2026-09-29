"""Authentication and role authorisation (PRD section 2.1, rejection precedence 1 and 2)."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from db import ROLES
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ALL_OPERATOR_ROLES = (
    "DeveloperPrincipal",
    "EntitlementOfficer",
    "ConstructionManager",
    "LeasingAgent",
    "AssetManager",
    "PropertyManager",
)


def authenticate():
    role = request.headers.get(USER_ROLE_HEADER)
    user_id = request.headers.get(USER_ID_HEADER)
    if role is None or not role.strip() or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is missing or not a known role")
    if role == "Household" and (user_id is None or not user_id.strip()):
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is required for a Household caller")
    g.role = role
    g.user_id = user_id
    return role, user_id


def endpoint(*roles):
    """Authenticate, then check the caller's role against this endpoint's role list."""

    def decorator(handler):
        @wraps(handler)
        def wrapper(*args, **kwargs):
            role, _ = authenticate()
            if role not in roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role %s may not invoke this operation" % role,
                )
            return handler(*args, **kwargs)

        return wrapper

    return decorator


def acting_user_id():
    return g.get("user_id")


def acting_role():
    return g.get("role")
