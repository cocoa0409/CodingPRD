"""Band 1 (authentication), band 2 (role authorization) and band 5 (ownership)."""
from flask import g, request

from errors import ApiError

ROLES = (
    "ProgramAdministrator",
    "ConcessionSpecialist",
    "ContractingOfficer",
    "EvaluationPanelist",
    "AuditorGeneral",
    "Concessionaire",
)

ALL_ROLES = ROLES
PANEL_READERS = (
    "ProgramAdministrator",
    "ConcessionSpecialist",
    "ContractingOfficer",
    "EvaluationPanelist",
    "AuditorGeneral",
)


def guard(*roles):
    """Authenticate, then authorize. Both run before anything else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid identity headers")
    g.user_id = user_id
    g.role = role
    if roles and role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s is not authorized for this endpoint" % role)
    return user_id


def acting_user():
    return g.user_id


def acting_role():
    return g.role


def require_owner(offeror_id):
    """Band 5 — only a Concessionaire is subject to the ownership check."""
    if g.role == "Concessionaire" and g.user_id != offeror_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own this resource")


def fetch(collection, row_id, not_found_error):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(not_found_error, "Resource not found")
    return row
