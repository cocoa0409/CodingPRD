"""Identity headers and role enforcement (PRD section 2.1, ladder rungs 1-2)."""
import functools

from flask import request

from errors import ApiError

ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "Evaluator",
    "PlacementAdministrator",
    "Parent",
    "DistrictAdmin",
)


def current_user_id():
    return (request.headers.get("X-User-ID") or "").strip()


def current_role():
    return (request.headers.get("X-User-Role") or "").strip()


def require_identity():
    """Rung 1: no identity header at all -> 401, before any path resolution."""
    if not current_user_id():
        raise ApiError(
            "ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty"
        )


def require_role(allowed):
    """Rung 2: unknown or unauthorised role -> 403, before body validation."""
    role = current_role()
    if not role or role not in ROLES or role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role '%s' may not perform this operation" % (role or "<missing>"),
        )
    return role


def endpoint(*allowed):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            require_role(allowed)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
