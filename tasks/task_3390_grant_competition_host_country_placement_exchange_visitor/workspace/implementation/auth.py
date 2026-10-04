"""Authentication and authorization primitives (PRD 2.1, 2.7 priorities 1/2/5).

Every request carries X-User-ID and X-User-Role. Missing headers or a role
outside the seven declared roles is ERR_UNAUTHENTICATED (401). A role not
admitted by the endpoint is ERR_UNAUTHORIZED (403). For Applicant-role calls,
X-User-ID must equal the owning applicant's id, else ERR_NOT_RESOURCE_OWNER.
"""

from flask import request

from constants import ROLES, ROLE_APPLICANT
from errors import ApiError


def auth():
    """Priority 1: presence and validity of the two auth headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_roles(role, allowed):
    """Priority 2: the caller's role is admitted by the endpoint."""
    if role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            403,
            "Role %s is not permitted for this endpoint" % role,
        )


def check_owner(role, user_id, owner_applicant_id):
    """Priority 5: Applicant-role callers may only touch their own resources.
    Non-applicant roles have opaque identities and are never owner-checked."""
    if role == ROLE_APPLICANT and user_id != owner_applicant_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            403,
            "Applicant-role caller is not the owner of this resource",
        )
