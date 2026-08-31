"""Authentication / RBAC middleware."""
import functools

from flask import g, request

from errors import ApiError

ROLES = [
    "UtilityForester",
    "ContractorPlanner",
    "CrewForeman",
    "CertifiedArborist",
    "CustomerAdvocate",
    "BillingAnalyst",
    "PlatformAdmin",
]

ALL_ROLES = list(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or invalid")
    g.user_id = str(user_id)
    g.role = role
    return g.user_id, g.role


def endpoint(roles):
    """Decorator: priority 1 (401) then priority 2 (403)."""
    allowed = list(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED",
                               "role %s may not call this operation" % g.role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def actor_id():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "role", None)
