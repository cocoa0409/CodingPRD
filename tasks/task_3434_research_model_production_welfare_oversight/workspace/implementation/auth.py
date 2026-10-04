"""Authentication (PRD 2.1): X-User-ID + X-User-Role headers, role checks,
and Customer-ownership checks."""
from flask import request

from responses import ApiError

ROLES = [
    "PlatformAdmin",
    "FacilityManager",
    "Veterinarian",
    "IACUCReviewer",
    "Customer",
    "LogisticsCoordinator",
    "WelfareInspector",
]

ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: both headers present and the role is one of the seven."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return uid, role


def require_role(role, allowed):
    """Priority 2: the caller role is listed for the endpoint/transition."""
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE",
            403,
            "Role %s is not authorized for this operation" % role,
        )


def require_ownership(uid, owner_id):
    """Priority 3: a Customer-role caller may act only on its own resources."""
    if uid != owner_id:
        raise ApiError(
            "ERR_OWNERSHIP_MISMATCH",
            403,
            "Customer identity does not own this resource",
        )
