"""Authentication, RBAC, ownership and segregation of duties (PRD SS2.1)."""
import functools

from flask import g, request

from constants import (
    ALL_ROLES,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    ROLE_PLATFORM_ADMIN,
    ROLE_TALENT_AGENT,
)
from errors import ApiError


def authenticate():
    """Rung 1 -- checked before anything else, on reads as well as writes."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def check_role(allowed):
    """Rung 2 -- PlatformAdmin is permitted on every endpoint."""
    role = g.user_role
    if role == ROLE_PLATFORM_ADMIN:
        return
    if allowed is ALL_ROLES or role in allowed:
        return
    raise ApiError("ERR_ROLE_NOT_PERMITTED")


def endpoint(roles):
    """Wrap a view with rung 1 (auth) then rung 2 (role) enforcement."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            check_role(roles)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def user_id():
    return g.user_id


def user_role():
    return g.user_role


def require_talent_ownership(voice_talent_id):
    """Rung 7 -- TalentAgent identity IS the acting VoiceTalent.id."""
    if g.user_role != ROLE_TALENT_AGENT:
        return
    if g.user_id != voice_talent_id:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")


def require_distinct_actor(other_user_id):
    """Rung 8 -- segregation of duties, keyed on X-User-ID regardless of role."""
    if other_user_id is not None and g.user_id == other_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
