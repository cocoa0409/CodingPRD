"""Auth middleware: header extraction and role checking (PRD §2.1, scaffold §1.4 p1-2)."""

from flask import request

from errors import ApiError, ERR_AUTH, ERR_FORBIDDEN

VALID_ROLES = {
    "NetworkAdmin",
    "IntakeCoordinator",
    "ReferringPhysician",
    "ReviewCommitteeMember",
    "BillingSpecialist",
    "CareCoordinator",
    "OutreachPlanner",
    "PhilanthropyOfficer",
}


def require_auth(allowed_roles):
    """Validate X-User-ID / X-User-Role headers, then role authorization.
    Header check always runs before the role check (PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(ERR_AUTH, 400, "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in VALID_ROLES:
        raise ApiError(ERR_AUTH, 400, "X-User-Role header carries an unrecognized role")
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")
    return user_id, role
