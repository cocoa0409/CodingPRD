"""Auth middleware: header extraction + RBAC role checks (validation priorities 1-2)."""
from flask import g, request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = {
    "GrantAdministrator",
    "FrontDeskStaff",
    "Clinician",
    "BillingSpecialist",
    "CareCoordinator",
    "SupplyCoordinator",
    "PrivacyOfficer",
}


def authenticate():
    """Priority 1: X-User-ID and X-User-Role must be present and valid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing or invalid",
            400,
        )
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(allowed):
    """Priority 2: role permission check per RBAC matrix."""
    if g.role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted for this operation",
            403,
        )
