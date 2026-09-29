"""Header extraction and role-based access control (PRD 2.1).

Every request carries X-User-ID (the acting user) and X-User-Role (the role under
which the user acts). Authorization is decided from the header alone.
"""

from flask import request

from errors import ApiError
from store import db

ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_INTAKE_COORDINATOR = "IntakeCoordinator"
ROLE_UR_NURSE = "UtilizationReviewNurse"
ROLE_ATTENDING_PHYSICIAN = "AttendingPhysician"
ROLE_REVENUE_ANALYST = "RevenueIntegrityAnalyst"

ALL_ROLES = (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_INTAKE_COORDINATOR,
    ROLE_UR_NURSE,
    ROLE_ATTENDING_PHYSICIAN,
    ROLE_REVENUE_ANALYST,
)

SYSTEM_ACTOR = "SYSTEM"


def acting_role():
    return request.headers.get("X-User-Role")


def acting_user_id():
    value = request.headers.get("X-User-ID")
    return value if value is not None else ""


def require_role(*allowed):
    """PRD 2.8 rule 2: X-User-Role names a declared role permitted on this endpoint."""
    role = acting_role()
    if role is None or role not in ALL_ROLES or role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role is not permitted to invoke this endpoint.")
    return role


def acting_physician():
    """PRD 2.1: for an AttendingPhysician, X-User-ID is the id of the acting Physician row."""
    physician = db.physicians.get(acting_user_id())
    if physician is None:
        raise ApiError("ERR_PHYSICIAN_NOT_FOUND",
                       "The acting X-User-ID does not correspond to any Physician.")
    return physician
