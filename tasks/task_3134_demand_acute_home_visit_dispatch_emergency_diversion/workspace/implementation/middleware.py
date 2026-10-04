"""Auth middleware: identity header extraction and role gating per scaffold §1.4 p1/p2."""
from flask import request

from errors import raise_err, ERR_AUTH_HEADER, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "TriageNurse",
    "Dispatcher",
    "CareTeamMember",
    "AdvancedPracticeProvider",
    "FieldTechnician",
    "SupervisingPhysician",
    "BillingSpecialist",
    "PayerAdjudicator",
}


def get_identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (user_id is None or not isinstance(user_id, str) or user_id.strip() == ""
            or role is None or not isinstance(role, str) or role.strip() == ""):
        raise_err(ERR_AUTH_HEADER,
                  "X-User-ID and X-User-Role headers must be present and parseable")
    return user_id, role


def require_roles(allowed):
    """Validate identity headers and endpoint role permission."""
    user_id, role = get_identity()
    if role not in ROLES or role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role not permitted on this endpoint")
    return user_id, role
