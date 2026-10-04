"""Authentication / RBAC helpers (PRD section 2.1).

Every request carries X-User-ID and X-User-Role. Missing either header, or a
role value outside the seven declared roles, yields ERR_UNAUTHENTICATED (401).
An authenticated role not authorized for the endpoint yields
ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {
    "AdmissionsCounselor",
    "EligibilityReviewer",
    "EnrollmentManager",
    "ResidentialAdvisor",
    "CareerInstructor",
    "TransitionSpecialist",
    "OperatorAdmin",
}

ALL_ROLES = frozenset(ROLES)


def authenticate():
    """Priority 1: headers present and role declared. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError(
            ERR_UNAUTHENTICATED[0],
            ERR_UNAUTHENTICATED[1],
            "X-User-ID and X-User-Role headers are required",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED[0],
            ERR_UNAUTHENTICATED[1],
            "X-User-Role does not name a declared role",
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 2: acting role must be listed for the endpoint."""
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE[0],
            ERR_FORBIDDEN_ROLE[1],
            "Role {} is not authorized for this endpoint".format(role),
        )
