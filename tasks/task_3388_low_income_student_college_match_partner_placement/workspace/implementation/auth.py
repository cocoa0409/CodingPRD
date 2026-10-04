"""Authentication and role authorization (PRD section 2.1, priorities 2-3).

Every request carries X-User-Role (one of the six declared roles) and, for
every role except Anonymous, X-User-ID. Identity bindings:
  Student        -> X-User-ID is a Student id
  Counselor      -> X-User-ID is a Counselor id
  PartnerStaff   -> X-User-ID is a CommunityPartner id
  CollegeOfficer -> X-User-ID is a PartnerCollege id
  ProgramAdmin   -> opaque operator identifier
  Anonymous      -> no X-User-ID required
"""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = ("Anonymous", "ProgramAdmin", "Student", "Counselor", "PartnerStaff", "CollegeOfficer")

# Roles allowed on the broad read endpoints ("all GET endpoints" minus the
# restricted ones listed per endpoint table).
ALL_AUTHENTICATED = ("ProgramAdmin", "Student", "Counselor", "PartnerStaff", "CollegeOfficer")


def identity():
    """Priority 2: authenticate the two identity headers."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "missing or undeclared X-User-Role")
    if role != "Anonymous" and (uid is None or uid == ""):
        raise ApiError(ERR_UNAUTHENTICATED, "missing X-User-ID")
    return role, uid


def require_roles(role, allowed):
    """Priority 3 (role membership part): the role must be listed for the
    endpoint."""
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, "role %s is not permitted on this endpoint" % role)


def forbid(message="entity-backed ownership check failed"):
    """Priority 3 (ownership part)."""
    raise ApiError(ERR_UNAUTHORIZED, message)
