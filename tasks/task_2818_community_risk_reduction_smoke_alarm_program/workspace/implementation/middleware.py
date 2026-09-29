"""Auth header extraction and role authorization (PRD 2.1, ladder steps 1-2)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "RiskAnalyst",
    "CanvassCoordinator",
    "CrrTechnician",
    "GrantOfficer",
    "PartnerLiaison",
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(allowed):
    if g.role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")


def endpoint(*allowed):
    """Wrap a view so that ladder step 1 (authentication) always precedes
    step 2 (role authorization) and both precede any other work."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(allowed)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


ALL_ROLES = ROLES
