"""Auth middleware: header extraction and role checking per PRD §2.1."""
from __future__ import annotations

from flask import request

from errors import err_unauthenticated, err_unauthorized

ROLES = {
    "RegistrationCoordinator",
    "ComplianceAuditor",
    "EntityComplianceOfficer",
    "CIPAssetManager",
    "RegionalEntityReviewer",
    "FederalReviewer",
}

# Roles whose X-User-ID is an entity id (ownership checks apply)
ENTITY_BACKED_ROLES = {"EntityComplianceOfficer", "CIPAssetManager"}


def get_caller():
    """Extract and validate the X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED on missing/malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err_unauthenticated()
    if not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id.strip(), role


def require_roles(*allowed):
    """Return (user_id, role), raising ERR_UNAUTHORIZED if role not allowed."""
    user_id, role = get_caller()
    if role not in allowed:
        raise err_unauthorized()
    return user_id, role
