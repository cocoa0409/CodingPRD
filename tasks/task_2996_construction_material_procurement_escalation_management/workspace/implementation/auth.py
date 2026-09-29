"""Header authentication and role authorization (PRD 2.1, 2.9 rungs 1-2)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "BuyoutManager",
    "SupplierRep",
    "ProjectExecutive",
    "DesignEngineer",
    "OwnerRep",
)

ALL_ROLES = list(ROLES)
READ_ROLES = list(ROLES)


def authorize(*roles):
    """Rung 1 (ERR_UNAUTHENTICATED) then rung 2 (ERR_UNAUTHORIZED)."""
    allowed = set(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or role is None:
                raise ApiError("ERR_UNAUTHENTICATED")
            user_id = user_id.strip()
            role = role.strip()
            if not user_id or not role or role not in allowed_roles_universe:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


allowed_roles_universe = set(ROLES)


def current_user_id():
    return g.user_id


def current_role():
    return g.role
