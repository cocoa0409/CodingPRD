"""Auth / RBAC / ownership helpers (PRD §2.1, validation priorities 1-3)."""
from flask import request

from util import ApiError

ALL_ROLES = [
    "PlatformAdmin",
    "LenderOfficer",
    "ServicerOfficer",
    "FhaReviewer",
    "FhaApprover",
    "ClaimsExaminer",
]
ENTITY_ROLES = ("LenderOfficer", "ServicerOfficer")


def authenticate():
    """Priority 1: both headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role headers are required and the role must be recognized")
    return uid, role


def require_role(role, allowed):
    """Priority 2: role permitted for this endpoint / action."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED_ROLE",
                       "role %s is not permitted for this operation" % role)


def check_ownership(uid, role, lender_id):
    """Priority 3: entity-backed callers must own the lender of the target."""
    if role in ENTITY_ROLES and uid != lender_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP",
                       "caller does not own the lender of the target resource")
