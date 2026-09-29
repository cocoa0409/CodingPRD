"""Header-based authentication and RBAC (PRD 2.1)."""
import functools

from flask import g, request

from errors import fail

ROLES = (
    "PlatformAdmin",
    "SalesRep",
    "PermitCoordinator",
    "DispatchPlanner",
    "DriverOperator",
    "ComplianceOfficer",
    "CustomerContact",
)

ALL_ROLES = ROLES


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def endpoint(roles):
    """Validation priorities 1 and 2: authentication then role authorization."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                fail("ERR_ROLE_NOT_PERMITTED")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "role", None)
