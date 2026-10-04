"""Auth middleware (PRD 2.1).

X-User-ID and X-User-Role headers must both be present and non-empty
(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400). The role must be listed for
the endpoint (ERR_FORBIDDEN_ROLE, 403). The seven operational roles are below;
"Any" is never sent by a client and marks read-only endpoints callable by any
authenticated operational role.
"""
from flask import request

from errors import err

OPERATIONAL_ROLES = (
    "PlatformAdmin",
    "ProcessEngineer",
    "ManufacturingOperator",
    "QualityControlAnalyst",
    "QualityAssuranceReviewer",
    "SupplyPlanner",
    "RegulatoryAffairsSpecialist",
)


def require_auth(allowed_roles):
    """Validate headers and endpoint role membership. Returns X-User-ID.

    allowed_roles is a tuple of role names; the sentinel "Any" means any of
    the seven operational roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty")
    if "Any" in allowed_roles:
        if role not in OPERATIONAL_ROLES:
            err("ERR_FORBIDDEN_ROLE", "Role is not permitted to call this endpoint")
    elif role not in allowed_roles:
        err("ERR_FORBIDDEN_ROLE", "Role is not permitted to call this endpoint")
    return user_id
