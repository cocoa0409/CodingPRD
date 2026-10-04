"""Auth middleware and ownership checks (PRD §2.1, §2.8 tiers 1-4, §2.9).

Headers: X-User-ID and X-User-Role must both be present, and the role must be
one of the six declared roles, else ERR_MISSING_AUTH (401). A valid role not
in the endpoint's authorized list is ERR_FORBIDDEN_ROLE (403). When the role
is Applicant, X-User-ID is the id of the acting Applicant entity and
ownership checks compare it against the resource's applicant foreign key,
else ERR_NOT_RESOURCE_OWNER (403).
"""

from flask import request

from errors import api_err

ROLES = (
    "SystemAdmin",
    "Applicant",
    "Reviewer",
    "DistrictEngineer",
    "AgencyReviewer",
    "EnforcementOfficer",
)


def authenticate():
    """Pipeline tier 1: header presence and role membership."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise api_err("ERR_MISSING_AUTH",
                      "X-User-ID and X-User-Role headers are required and the "
                      "role must be one of the six declared roles")
    return user_id, role


def require_roles(allowed):
    """Pipeline tiers 1-2: authenticate, then check endpoint role list."""
    user_id, role = authenticate()
    if role not in allowed:
        raise api_err("ERR_FORBIDDEN_ROLE",
                      "Role %s is not authorized for this endpoint" % role)
    return user_id, role


def check_ownership(user_id, role, owner_applicant_id):
    """Pipeline tier 4: Applicant callers must own the target resource."""
    if role == "Applicant" and user_id != owner_applicant_id:
        raise api_err("ERR_NOT_RESOURCE_OWNER",
                      "The calling applicant does not own this resource")
