"""Authentication, authorization and ownership rungs of the evaluation ladder."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "LivestockOwner",
    "FieldInspector",
    "BrandRecorder",
    "FeeAdministrator",
    "TheftInvestigator",
    "BoardAdmin",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    """Rung 1: both context headers present and the role is one the board recognises."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a declared board role.")
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def authorize(allowed_roles):
    """Rung 2: the acting role appears in the called endpoint's role list."""
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not call this operation." % g.role)


def endpoint(*allowed_roles):
    """Decorator applying rungs 1 and 2 before the handler body runs."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(allowed_roles)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def caller_id():
    return g.user_id


def caller_role():
    return g.role


def require_owner(expected_owner_id):
    """Rung 6 for the nine LivestockOwner-guarded writes."""
    if g.user_id != expected_owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The acting owner does not own this resource.")


def require_one_of(expected_ids):
    if g.user_id not in expected_ids:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The acting owner is not a party to this resource.")


def require_assigned_inspector(order):
    """Rung 6 for the four FieldInspector-guarded writes."""
    if g.user_id != order.get("inspector_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The acting inspector does not hold this order.")
