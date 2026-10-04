"""Authentication and role-based access control (PRD §2.1, §2.7 tiers 1-2).

Every request must carry ``X-User-ID`` and ``X-User-Role``. A missing header
or an undeclared role yields ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
A declared role not permitted on the endpoint yields ERR_FORBIDDEN (403), as
does a failed entity-backed ownership pin on X-User-ID.
"""
from flask import request

from errors import raise_err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN

ROLES = (
    "EstablishmentManager",
    "Inspector",
    "SupervisoryReviewer",
    "DistrictManager",
    "LabelOfficer",
    "RecallCoordinator",
    "ProgramAdministrator",
)


def user_context():
    """Validation pipeline tier 1: headers present, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return user_id, role


def require_roles(*allowed):
    """Tiers 1-2: user context, then role permission for this endpoint."""
    user_id, role = user_context()
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "role %s is not permitted on this endpoint" % role)
    return user_id, role


def require_ownership(user_id, pinned_value):
    """Entity-backed ownership pin: X-User-ID must equal the pinned id."""
    if pinned_value is None or user_id != pinned_value:
        raise_err(ERR_FORBIDDEN, "X-User-ID does not match the owning entity id")
