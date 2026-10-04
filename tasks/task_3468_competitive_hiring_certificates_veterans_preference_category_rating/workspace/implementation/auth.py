"""Auth header extraction and role authorization (PRD 2.1, validations p1-p2).

Headers: X-User-ID (identity) and X-User-Role (declared role).
Applicant identity is entity-backed: X-User-ID == Applicant.id.
All other roles are opaque operator ids.
"""
from flask import request

from errors import fail

ROLES = [
    "HRSpecialist",
    "HiringManager",
    "SME",
    "Applicant",
    "SelectingOfficial",
    "OPMDelegate",
    "SuitabilityReviewer",
    "SecurityAdjudicator",
    "PlatformAdmin",
]


def get_auth():
    """Priority 1: headers present and role declared, else 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str):
        fail("ERR_UNAUTHENTICATED", "missing X-User-ID header")
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or undeclared X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Priority 2 (role part): acting role must be listed for the endpoint."""
    if role not in allowed:
        fail("ERR_FORBIDDEN", "role %s not permitted on this endpoint" % role)


def require_applicant_owner(user_id, owner_applicant_id):
    """Entity-backed ownership: an Applicant acts only for itself (PRD 2.1)."""
    if user_id != owner_applicant_id:
        fail("ERR_FORBIDDEN", "applicant may act only on its own resources")
