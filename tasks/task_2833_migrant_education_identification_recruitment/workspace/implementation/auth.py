"""Caller identity and role authorization (validation ladder rungs 1 and 2)."""

import functools

from flask import g, request

from errors import ApiError
from store import store

ROLES = (
    "StateProgramAdmin",
    "Recruiter",
    "QualityControlReviewer",
    "ServiceCoordinator",
    "ExchangeLiaison",
)

ALL_ROLES = ROLES

# Roles backed by a persisted Recruiter row.
ENTITY_BACKED = ("Recruiter", "QualityControlReviewer")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or unrecognized")
    recruiter = None
    if role in ENTITY_BACKED:
        recruiter = store.recruiters.get(user_id)
        if recruiter is None:
            raise ApiError(
                "ERR_UNAUTHENTICATED",
                "X-User-ID does not resolve to a known recruiter",
            )
    g.user_id = user_id
    g.user_role = role
    g.recruiter = recruiter
    return user_id, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not permitted to perform this operation" % role,
        )


def require(*allowed):
    """Decorator running rung 1 then rung 2 before the view body."""
    if len(allowed) == 1 and isinstance(allowed[0], (list, tuple)):
        allowed_roles = tuple(allowed[0])
    else:
        allowed_roles = tuple(allowed)

    def decorate(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            authorize(role, allowed_roles)
            return view(*args, **kwargs)

        return wrapper

    return decorate


def read_only(view):
    """Every read endpoint is open to all five roles."""
    return require(ALL_ROLES)(view)


def caller_id():
    return g.get("user_id")


def caller_role():
    return g.get("user_role")


def caller_recruiter():
    return g.get("recruiter")
