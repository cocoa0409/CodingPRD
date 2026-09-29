"""Authentication, authorisation and ownership (PRD 2.1, 2.6 stages 1-3)."""

from flask import request

from errors import ApiError

ROLES = (
    "ComplianceOfficer",
    "BranchManager",
    "FieldInspector",
    "Applicator",
    "ClaimsAdjudicator",
    "PropertyOwner",
)

ALL_ROLES = ROLES
READ_ROLES = ROLES


def authenticate(allowed_roles):
    """Stage 1 then stage 2 of the rejection ladder.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED", 403, "%s is not a declared role" % role)
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "role %s may not perform this operation" % role)
    return user_id, role


def not_owner(message="Caller does not own this resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, message)


def require_owner(actual_owner_id, user_id, message=None):
    if actual_owner_id != user_id:
        raise not_owner(message or "Caller is not the owner of this resource")
