"""Role-Based Access Control (PRD §2.1, §2.8 priorities 1-2).

Every request carries X-User-ID and X-User-Role. Missing headers or an unknown
role name -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). A valid role not
admitted by the endpoint -> ERR_FORBIDDEN_FOR_ROLE (403).

Identity semantics: FleetManager's X-User-ID is the acting Fleet's id;
ServiceAdvisor's X-User-ID is the acting ServiceCenter's id; the other five
roles carry opaque operator identifiers. Ownership comparisons live in the
endpoint modules (validation priority 5).
"""
from flask import request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "CertificationEngineer",
    "RegulatoryOfficer",
    "FleetManager",
    "ServiceAdvisor",
    "WarrantyAdjudicator",
    "RemanPlanner",
)

ANY = ROLES  # "Any" in the endpoint table: every declared role is admitted


def auth(allowed):
    """Validation pipeline stages 1-2. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and X-User-Role must name a declared role",
        )
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            403,
            "Role %s is not admitted to this endpoint" % role,
        )
    return uid, role
