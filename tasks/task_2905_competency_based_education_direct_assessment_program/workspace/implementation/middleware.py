"""Authentication, role authorization and ownership (PRD 2.1)."""
from flask import request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_REGISTRAR = "Registrar"
ROLE_STUDENT = "Student"
ROLE_FACULTY_MENTOR = "FacultyMentor"
ROLE_EVALUATOR = "Evaluator"
ROLE_INTEGRITY_OFFICER = "IntegrityOfficer"
ROLE_FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    ROLE_REGISTRAR,
    ROLE_STUDENT,
    ROLE_FACULTY_MENTOR,
    ROLE_EVALUATOR,
    ROLE_INTEGRITY_OFFICER,
    ROLE_FINANCIAL_AID_OFFICER,
    ROLE_PLATFORM_ADMIN,
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def is_student(self):
        return self.role == ROLE_STUDENT

    def is_mentor(self):
        return self.role == ROLE_FACULTY_MENTOR

    def is_evaluator(self):
        return self.role == ROLE_EVALUATOR


def _header(name):
    raw = request.headers.get(name, None)
    if raw is None:
        return None
    if raw.strip() == "":
        return None
    return raw.strip()


def authenticate():
    """Header validation runs before any payload parsing."""
    user_id = _header(USER_ID_HEADER)
    role = _header(USER_ROLE_HEADER)
    if user_id is None or role is None:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Both %s and %s must be present and non-empty."
            % (USER_ID_HEADER, USER_ROLE_HEADER),
        )
    if role not in ALL_ROLES:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Unrecognised role '%s'." % role)
    return Caller(user_id, role)


def require(*allowed_roles):
    """Authenticate then authorise the caller against the endpoint's roles."""
    caller = authenticate()
    if allowed_roles and caller.role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role '%s' may not perform this operation." % caller.role,
        )
    return caller


def deny_not_owner(message="The acting identity does not own this resource."):
    raise ApiError("ERR_NOT_RESOURCE_OWNER", message)


def check_student_ownership(caller, student_id):
    """Ownership for a Student caller against a subject student id."""
    if caller.role == ROLE_STUDENT and student_id != caller.user_id:
        deny_not_owner()


def check_mentor_ownership(caller, mentor_id):
    if caller.role == ROLE_FACULTY_MENTOR and mentor_id != caller.user_id:
        deny_not_owner()


def check_evaluator_ownership(caller, evaluator_id):
    if caller.role == ROLE_EVALUATOR and evaluator_id != caller.user_id:
        deny_not_owner()
