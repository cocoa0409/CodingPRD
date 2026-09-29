"""Acting identity and role-based access control (PRD section 2.1).

Ranks 1-2 (authentication), rank 3 (role authorization) and rank 4 (ownership)
of the validation precedence in PRD section 2.9 live here.
"""

from flask import request

from db import S
from errors import ApiError

ROLE_HEADER = "X-User-Role"
USER_ID_HEADER = "X-User-ID"

ROLE_INTEGRITY_OFFICER = "IntegrityOfficer"
ROLE_FACULTY_REPORTER = "FacultyReporter"
ROLE_PANEL_CHAIR = "PanelChair"
ROLE_STUDENT = "Student"
ROLE_APPEALS_DEAN = "AppealsDean"
ROLE_REGISTRAR_OFFICER = "RegistrarOfficer"

ALL_ROLES = (
    ROLE_INTEGRITY_OFFICER,
    ROLE_FACULTY_REPORTER,
    ROLE_PANEL_CHAIR,
    ROLE_STUDENT,
    ROLE_APPEALS_DEAN,
    ROLE_REGISTRAR_OFFICER,
)

# Roles whose X-User-ID is the id of a stored row.
FACULTY_BACKED_ROLES = (ROLE_FACULTY_REPORTER, ROLE_PANEL_CHAIR)
STUDENT_BACKED_ROLES = (ROLE_STUDENT,)

# Roles that are opaque: X-User-ID is never resolved against stored rows.
OPAQUE_ROLES = (ROLE_INTEGRITY_OFFICER, ROLE_APPEALS_DEAN, ROLE_REGISTRAR_OFFICER)


class Actor(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    def __repr__(self):
        return "Actor(%r, %r)" % (self.role, self.user_id)


def _blank(value):
    return value is None or value.strip() == ""


def authenticate():
    """Ranks 1-2: resolve the acting identity or raise ERR_UNAUTHENTICATED."""
    role = request.headers.get(ROLE_HEADER)
    if _blank(role):
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is required.")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role names an unknown role.")
    user_id = request.headers.get(USER_ID_HEADER)
    read_only = request.method == "GET"
    if _blank(user_id):
        # Narrow tolerance: the three opaque roles may omit X-User-ID on
        # read-only endpoints because they are not tied to any stored record.
        if read_only and role in OPAQUE_ROLES:
            return Actor(role, None)
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is required.")
    if role in FACULTY_BACKED_ROLES and user_id not in S.faculty_members:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID resolves to no faculty member.")
    if role in STUDENT_BACKED_ROLES and user_id not in S.students:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID resolves to no student.")
    return Actor(role, user_id)


def require_role(actor, allowed):
    """Rank 3: the resolved role must appear in the endpoint's authorized set."""
    if actor.role not in allowed:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not permitted on this endpoint." % actor.role,
        )


def guard(actor, allowed):
    require_role(actor, allowed)
    return actor


def auth(allowed):
    actor = authenticate()
    require_role(actor, allowed)
    return actor


def require_owner(actor, expected_id):
    """Rank 4: the acting identity must be the owner the endpoint demands."""
    if expected_id is None or actor.user_id != expected_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "The acting identity is not the owner of this resource.",
        )
