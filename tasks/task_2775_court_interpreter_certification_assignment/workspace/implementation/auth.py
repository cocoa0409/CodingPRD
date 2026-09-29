"""Authentication and role authorization (PRD 2.1, ladder priorities 1 and 2)."""
from flask import request

from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "CredentialingOfficer",
    "SchedulingCoordinator",
    "FiscalOfficer",
    "QualityReviewer",
    "Interpreter",
)


def actor():
    """The acting (user_id, role) pair, rejecting anything malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    return str(user_id).strip(), role


def require(*allowed):
    """Authenticate, then authorize the acting role for this endpoint."""
    user_id, role = actor()
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorized for this operation." % role,
        )
    return user_id, role
