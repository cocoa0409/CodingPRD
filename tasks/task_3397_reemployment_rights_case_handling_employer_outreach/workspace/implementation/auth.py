"""Authentication (X-User-Role / X-User-ID) and role authorization."""
from flask import request

from errors import ApiError

ROLES = {
    "Anonymous",
    "ServiceMember",
    "Employer",
    "Ombudsman",
    "ProgramCoordinator",
    "AgencyReviewer",
}


def actor():
    """Validate the two mandatory headers. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401, "Missing or unknown X-User-Role header"
        )
    if role != "Anonymous" and (uid is None or uid == ""):
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "X-User-ID header is required for role %s" % role,
        )
    return role, uid


def require_role(*roles):
    """Endpoint-level role list check (validation priority 2)."""
    role, uid = actor()
    if role not in roles:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE",
            403,
            "Role %s is not authorized for this endpoint" % role,
        )
    return role, uid


def require_ownership(condition):
    if not condition:
        raise ApiError(
            "ERR_OWNERSHIP_VIOLATION",
            403,
            "Actor does not own the target resource",
        )
