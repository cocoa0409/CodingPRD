"""Authentication and role authorization (PRD section 2.1).

Every request must carry X-User-ID and X-User-Role. A missing header or an
undeclared role is ERR_UNAUTHENTICATED (401); a declared role not listed for
the endpoint is ERR_UNAUTHORIZED (403).
"""
from flask import request

from errors import fail

ROLES = (
    "SourcingManager",
    "SustainabilityAuditor",
    "AuditVerifier",
    "DairyProgramManager",
    "FlavorManager",
    "PlantScheduler",
    "IndependentBoardMember",
    "ParentOpsController",
    "FranchiseAdmin",
    "ShopOperator",
    "Fan",
)


def authenticate():
    """Return (user_id, role) or fail with ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED",
             "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def authorize(role, allowed):
    """Fail with ERR_UNAUTHORIZED unless role is in allowed."""
    if role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role not permitted for this endpoint")
