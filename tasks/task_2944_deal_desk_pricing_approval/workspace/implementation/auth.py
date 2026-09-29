"""Authentication and role authorisation (PRD 2.1, precedence steps 1-2)."""
import functools

from flask import request

from errors import fail

ROLES = (
    "SalesRep",
    "DealDeskAnalyst",
    "SalesDirector",
    "VPSales",
    "CFO",
    "LegalCounsel",
    "RevenueAccountant",
    "PlatformAdmin",
)

ALL_ROLES = ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def check_authentication():
    """Both headers present and non-empty, before anything else is examined."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not user_id.strip():
        fail("ERR_UNAUTHENTICATED", "The X-User-ID header is required.")
    if role is None or not role.strip():
        fail("ERR_UNAUTHENTICATED", "The X-User-Role header is required.")


def current_user_id():
    value = request.headers.get(USER_ID_HEADER)
    return value.strip() if value else value


def current_role():
    value = request.headers.get(USER_ROLE_HEADER)
    return value.strip() if value else value


def require_roles(*allowed):
    """Decorator enforcing the endpoint's authorised role list."""
    if len(allowed) == 1 and isinstance(allowed[0], (list, tuple)):
        allowed = tuple(allowed[0])

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            role = current_role()
            if role not in allowed:
                fail(
                    "ERR_FORBIDDEN_ROLE",
                    "Role %s may not call this endpoint." % role,
                )
            return view(*args, **kwargs)

        wrapper.allowed_roles = allowed
        return wrapper

    return decorator
