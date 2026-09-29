"""Authentication and role-based access control (PRD 2.1, ladder rungs 1-2)."""
from flask import g, request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "ApplicationEngineer",
    "ProductionPlanner",
    "QualityInspector",
    "ServiceManager",
    "CustomerContact",
)

ALL_ROLES = set(ROLES)


def authorize(allowed_roles):
    """Rung 1 then rung 2.  Returns the acting (user_id, role) pair."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED",
                       "The X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED",
                       "The X-User-Role header is required.")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED_ROLE",
                       "Unknown role '%s'." % role)
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE",
                       "Role '%s' may not call this endpoint." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def is_customer_contact(role):
    return role == "CustomerContact"


def require_owner(role, user_id, customer_id):
    """Rung 5 -- the CustomerContact ownership check."""
    if role == "CustomerContact" and user_id != customer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting customer contact does not own this resource.")
