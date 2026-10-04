"""Caller-context authentication and role authorization (PRD section 2.1,
validation priorities 1 and 2)."""
from flask import request

from errors import raise_err

ROLES = {
    "PlatformAdmin",
    "AgencyAdmin",
    "TreasuryOfficer",
    "ComplianceAuditor",
    "Payer",
    "Anonymous",
}


def caller(allowed_roles):
    """Validate X-User-ID / X-User-Role, then role authorization.

    Returns (user_id, role). Priority 1: missing header or undeclared role ->
    ERR_MISSING_OR_INVALID_USER_CONTEXT (400). Priority 2: role not listed for
    the endpoint -> ERR_FORBIDDEN_FOR_ROLE (403).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            400,
            "X-User-ID and X-User-Role headers must be present and "
            "X-User-Role must be a declared role",
        )
    if role not in allowed_roles:
        raise_err(
            "ERR_FORBIDDEN_FOR_ROLE",
            403,
            "Role %s is not authorized for this endpoint" % role,
        )
    return uid, role
