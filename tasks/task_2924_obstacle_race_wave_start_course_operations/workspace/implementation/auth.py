"""Rungs 1-2 of the evaluation ladder (PRD 2.6): authentication and role.

Headers are exactly X-User-ID and X-User-Role (PRD 2.1).  For operator roles
X-User-ID is opaque; for Participant it is the id of the acting Participant row.
"""

from flask import g, request

from errors import fail

PERMIT_OFFICER = "PermitOfficer"
COURSE_DESIGNER = "CourseDesigner"
RACE_DIRECTOR = "RaceDirector"
SAFETY_OFFICER = "SafetyOfficer"
SITE_OPS_LEAD = "SiteOpsLead"
OBSTACLE_MARSHAL = "ObstacleMarshal"
PARTICIPANT = "Participant"

ALL_ROLES = (
    PERMIT_OFFICER,
    COURSE_DESIGNER,
    RACE_DIRECTOR,
    SAFETY_OFFICER,
    SITE_OPS_LEAD,
    OBSTACLE_MARSHAL,
    PARTICIPANT,
)

# Convenience bundles used by the read endpoints.
OPERATOR_READERS = (
    PERMIT_OFFICER,
    COURSE_DESIGNER,
    RACE_DIRECTOR,
    SAFETY_OFFICER,
    SITE_OPS_LEAD,
)


def authenticate():
    """Rung 1: both headers present and non-empty, role one of the seven."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    user_id = user_id.strip() if isinstance(user_id, str) else None
    role = role.strip() if isinstance(role, str) else None
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a declared role." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*allowed_roles):
    """Rungs 1 then 2: authenticate, then check the endpoint's role list."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        fail(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not authorised for this operation." % role,
        )
    return user_id, role
