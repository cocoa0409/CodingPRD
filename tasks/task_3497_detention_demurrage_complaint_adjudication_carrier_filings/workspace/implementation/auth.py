"""Auth: header presence + role validity (rung 1) and role authorization (rung 2)."""
from flask import request

from errors import (
    fail,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLES = (
    "CommissionAdmin",
    "CommissionDocket",
    "ComplianceReviewer",
    "OmbudsOfficer",
    "AdministrativeLawJudge",
    "EnforcementCounsel",
    "CarrierRep",
    "ShipperRep",
)


def context():
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role or role not in ROLES:
        fail(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
             "X-User-ID and X-User-Role headers are required and X-User-Role "
             "must name a declared role")
    return uid, role


def require_roles(*roles):
    """Rung 1 + rung 2 of the validation ladder."""
    uid, role = context()
    if role not in roles:
        fail(ERR_INSUFFICIENT_PERMISSIONS,
             "role %s is not authorized for this endpoint" % role)
    return uid, role


def any_role():
    """Read endpoints: any declared role may read."""
    return require_roles(*ROLES)
