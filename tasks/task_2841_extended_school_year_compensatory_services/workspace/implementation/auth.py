"""Authentication, role membership and ownership checks (PRD sections 2.1 / 2.7)."""
import functools

from flask import g, request

from errors import ApiError
from store import LOCK

CASE_MANAGER = "CaseManager"
PROGRAM_COORDINATOR = "ProgramCoordinator"
SPED_DIRECTOR = "SpedDirector"
COMPLIANCE_OFFICER = "ComplianceOfficer"
RELATED_SERVICE_PROVIDER = "RelatedServiceProvider"
PARENT_GUARDIAN = "ParentGuardian"

ALL_ROLES = (
    CASE_MANAGER,
    PROGRAM_COORDINATOR,
    SPED_DIRECTOR,
    COMPLIANCE_OFFICER,
    RELATED_SERVICE_PROVIDER,
    PARENT_GUARDIAN,
)

STAFF_ROLES = (CASE_MANAGER, PROGRAM_COORDINATOR, SPED_DIRECTOR, COMPLIANCE_OFFICER)


def endpoint(roles):
    """Guard 1 and 2 of PRD 2.7 for one route, then run the handler serially."""

    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not user_id.strip() or not role or not role.strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ALL_ROLES or role not in allowed:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            g.user_id = user_id
            g.role = role
            with LOCK:
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def is_guardian():
    return g.role == PARENT_GUARDIAN


def is_provider_role():
    return g.role == RELATED_SERVICE_PROVIDER


def guard_student_scope(student_id):
    """PRD 2.7 check 3, for paths that address a Student directly."""
    if is_guardian() and g.user_id != student_id:
        raise ApiError("ERR_NOT_STUDENT_GUARDIAN")


def guard_owned_record(record):
    """PRD 2.7 check 3, for records carrying a student_id."""
    if is_guardian() and g.user_id != record.get("student_id"):
        raise ApiError("ERR_NOT_STUDENT_GUARDIAN")
