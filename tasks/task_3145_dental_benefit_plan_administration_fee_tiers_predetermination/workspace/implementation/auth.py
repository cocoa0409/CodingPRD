"""Auth extraction, role gate, and ownership gates per PRD §2.1 / §2.10."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "PlanAdmin",
    "NetworkManager",
    "ClinicalReviewer",
    "ClaimsExaminer",
    "Member",
    "Provider",
}


def current_identity():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role / X-User-ID", 401)
    return user_id, role


def require_role(*roles):
    user_id, role = current_identity()
    if role not in roles:
        raise ApiError(ERR_UNAUTHORIZED, "Role not permitted on this endpoint", 403)
    return user_id, role


def require_any_authenticated():
    return current_identity()
