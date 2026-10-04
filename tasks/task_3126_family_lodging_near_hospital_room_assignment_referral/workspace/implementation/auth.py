"""Authentication and role authorization helpers (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = (
    "ProgramAdmin",
    "HouseManager",
    "HospitalReferrer",
    "FamilyContact",
    "VolunteerCoordinator",
)


def auth():
    """Return (user_id, role); raises 401 when headers missing/invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or unrecognized X-User-Role / X-User-ID headers")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "role %s not permitted for this endpoint" % role)
