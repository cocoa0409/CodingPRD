"""Authentication / RBAC middleware (PRD sections 2.1 and 2.6 rungs 1-3)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "ProductionCoordinator",
    "Adaptor",
    "NativeReviewer",
    "CastingDirector",
    "VoiceTalentUser",
    "MixEngineer",
    "PlatformAdmin",
)

ALL_ROLES = ROLES


def auth(*allowed_roles):
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            # rung 1: both headers present and non-empty
            if user_id is None or str(user_id).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            if role is None or str(role).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            # rung 2: role is one of the seven declared roles
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            # rung 3: role authorised for this endpoint
            if role not in allowed:
                raise ApiError("ERR_ROLE_FORBIDDEN")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
