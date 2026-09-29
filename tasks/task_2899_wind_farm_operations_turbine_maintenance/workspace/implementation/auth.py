"""Rungs 1 and 2 of the rejection ladder: authentication and role authorisation."""

from flask import request

from errors import ApiError

ROLES = (
    "SiteAdmin",
    "ControlRoomOperator",
    "MaintenancePlanner",
    "ReliabilityEngineer",
    "CrewLead",
    "CommercialManager",
)

ALL_ROLES = list(ROLES)
COMMERCIAL_READ_ROLES = ["SiteAdmin", "CommercialManager", "ReliabilityEngineer"]


def authenticate(allowed_roles):
    """Return (user_id, role) or raise the appropriate auth error."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required.")
    if user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must be non-empty.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role names an unknown role.")
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED", "Role %s is not authorised for this endpoint." % role
        )
    return user_id, role
