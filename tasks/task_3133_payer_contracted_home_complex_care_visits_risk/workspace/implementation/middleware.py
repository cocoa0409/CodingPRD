"""Auth middleware per PRD §2.1 and SCAFFOLD validations priorities 1-2."""
from flask import request

from errors import err_missing_headers, err_forbidden

ROLES = {
    "PlatformAdmin",
    "ContractAdministrator",
    "EngagementSpecialist",
    "CareCoordinator",
    "Clinician",
    "PerformanceAnalyst",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ApiError(400) if headers are missing/empty
    or role is not one of the six recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise err_missing_headers()
    if role is None or str(role).strip() == "":
        raise err_missing_headers()
    role = str(role).strip()
    if role not in ROLES:
        # An unrecognized role value means the role header is invalid.
        raise err_missing_headers()
    return str(user_id), role


def require_roles(allowed_roles):
    """Validate headers, then role authorization. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise err_forbidden()
    return user_id, role
