"""Authentication headers and role authorization (PRD sections 2.1 and 2.6)."""
from flask import request

from errors import raise_err

# The five declared roles (PRD section 2.1).
PERMIT_OFFICER = "PermitOfficer"
PERFORMER = "Performer"
AUDITION_PANELIST = "AuditionPanelist"
NOISE_INSPECTOR = "NoiseInspector"
RESIDENT = "Resident"

ROLES = {PERMIT_OFFICER, PERFORMER, AUDITION_PANELIST, NOISE_INSPECTOR, RESIDENT}


def authenticate():
    """Rejection precedence 1: both headers present and the role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role are required and X-User-Role must be a declared role",
        )
    return user_id, role


def require_roles(allowed):
    """Rejection precedence 1 then 2: authenticate, then authorize the role."""
    user_id, role = authenticate()
    if role not in allowed:
        raise_err("ERR_FORBIDDEN_ROLE", "Role %s is not authorized for this endpoint" % role)
    return user_id, role


def require_owner(role, user_id, owner_performer_id):
    """Rejection precedence 5: a Performer caller must own the target resource."""
    if role == PERFORMER and user_id != owner_performer_id:
        raise_err("ERR_NOT_RESOURCE_OWNER", "The target resource belongs to another performer")
