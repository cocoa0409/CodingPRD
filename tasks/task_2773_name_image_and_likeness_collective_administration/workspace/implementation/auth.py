"""Header contract and RBAC of PRD 2.1, at ladder priorities 1-3."""

from flask import request

from errors import ApiError

PLATFORM_ADMIN = "PlatformAdmin"
COLLECTIVE_DIRECTOR = "CollectiveDirector"
COMPLIANCE_OFFICER = "ComplianceOfficer"
INSTITUTION_REVIEWER = "InstitutionReviewer"
ATHLETE = "Athlete"
TREASURY_OFFICER = "TreasuryOfficer"

ALL_ROLES = [
    PLATFORM_ADMIN, COLLECTIVE_DIRECTOR, COMPLIANCE_OFFICER,
    INSTITUTION_REVIEWER, ATHLETE, TREASURY_OFFICER,
]
NON_ATHLETE_ROLES = [
    PLATFORM_ADMIN, COLLECTIVE_DIRECTOR, COMPLIANCE_OFFICER,
    INSTITUTION_REVIEWER, TREASURY_OFFICER,
]

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"


def authenticate(allowed_roles):
    """Priority 1 headers, priority 2 known role, priority 3 endpoint permission."""
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(USER_HEADER)
    if role is None or role == "" or user_id is None or user_id == "":
        raise ApiError("ERR_MISSING_AUTH_HEADER")
    if role not in ALL_ROLES:
        raise ApiError("ERR_INVALID_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return role, user_id
