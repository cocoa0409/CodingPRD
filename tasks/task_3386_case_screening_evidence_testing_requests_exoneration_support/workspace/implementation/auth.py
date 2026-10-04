"""Auth: user-context headers and role admission (PRD 2.1, 2.9 priorities 1-2)
plus the Client-role ownership check (priority 3.4).

Every request must carry X-User-ID and X-User-Role; the role must be one of
the eight declared names. For the Client role, X-User-ID is the id of the
acting Client record; for the seven staff roles it is an opaque identifier.
"""

from flask import request

from errors import (
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_OWNERSHIP_MISMATCH,
    ERR_UNAUTHORIZED_ROLE,
    raise_err,
)

ROLE_NAMES = (
    "PlatformAdmin",
    "IntakeSpecialist",
    "ManagingAttorney",
    "StaffAttorney",
    "EvidenceAnalyst",
    "ClientServicesAdvocate",
    "PolicyDirector",
    "Client",
)

STAFF_ROLES = tuple(r for r in ROLE_NAMES if r != "Client")


def user_context():
    """Priority 1: both headers present, non-empty, role in vocabulary."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (uid is None or not uid.strip()
            or role is None or not role.strip()
            or role not in ROLE_NAMES):
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers must both be present and "
                  "non-empty, and X-User-Role must be a declared role")
    return uid, role


def require_roles(*roles):
    """Priorities 1-2: user context, then role admission for the endpoint."""
    uid, role = user_context()
    if role not in roles:
        raise_err(ERR_UNAUTHORIZED_ROLE,
                  "Role %s is not authorized for this endpoint" % role)
    return uid, role


def require_ownership(ok):
    """Priority 3.4: Client-role ownership of the addressed resource."""
    if not ok:
        raise_err(ERR_OWNERSHIP_MISMATCH,
                  "Client-role caller does not own the addressed resource")
