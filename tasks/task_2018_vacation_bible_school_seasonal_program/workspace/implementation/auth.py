"""Authentication and role/ownership helpers (PRD §2.1, §2.9 priorities 1-2)."""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "Anonymous",
    "Parent",
    "Volunteer",
    "CheckInStaff",
    "RegistrationCoordinator",
    "VolunteerCoordinator",
    "SafetyOfficer",
    "ProgramDirector",
}


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: both headers present and the role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "missing or unknown X-User-Role / X-User-ID headers")
    return Ctx(user_id, role)


def require_role(ctx, *roles):
    """Priority 2 (role membership): the role must be listed for the endpoint."""
    if ctx.role not in roles:
        raise_err(ERR_FORBIDDEN, "role %s is not permitted on this endpoint" % ctx.role)


def forbid(message="ownership rule violated"):
    raise_err(ERR_FORBIDDEN, message)
