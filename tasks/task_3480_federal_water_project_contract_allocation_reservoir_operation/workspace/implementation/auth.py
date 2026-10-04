"""Authentication and role authorization (PRD section 2.1; validation steps 1-2).

Every request must carry X-User-ID and X-User-Role; the role must be one of the
seven declared roles. DistrictManager's X-User-ID is the acting District's id;
all other roles carry an opaque operator identifier.
"""
from flask import request

from errors import ApiError

ROLES = [
    "SystemAdmin",
    "ReclamationOperator",
    "HydrologyOfficer",
    "DistrictManager",
    "EnvironmentalOfficer",
    "FinanceOfficer",
    "RegionalDirector",
]

ALL_ROLES = list(ROLES)


def authenticate(allowed_roles):
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED / ERR_FORBIDDEN."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "missing or unknown X-User-ID / X-User-Role headers")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "role " + role + " is not permitted on this endpoint")
    return user_id, role
