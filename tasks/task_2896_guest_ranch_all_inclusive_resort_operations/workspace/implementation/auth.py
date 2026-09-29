"""Header authentication and role authorisation (PRD 2.1, precedence rules 1-3)."""

from flask import request

from errors import ApiError

ROLES = (
    "RanchManager",
    "ReservationsAgent",
    "HorseProgramDirector",
    "ActivityGuide",
    "Guest",
    "SafetyOfficer",
)

ALL_OPERATIONAL = (
    "RanchManager",
    "ReservationsAgent",
    "HorseProgramDirector",
    "ActivityGuide",
    "SafetyOfficer",
)

EVERYONE = ROLES


def auth(*allowed):
    """Resolve the caller, in the strict order missing-headers, unknown-role, unauthorized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS", "X-User-ID header is required.")
    if role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS", "X-User-Role header is required.")
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "Unknown role '%s'." % role)
    if allowed and role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED", "Role '%s' may not perform this operation." % role
        )
    return user_id.strip(), role
