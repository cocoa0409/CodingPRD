"""Authentication, role admission and patient scope (PRD 2.1, ladder 1-2, 17)."""
import functools

from flask import g, request

from errors import ApiError

PROGRAM_ADMIN = "ProgramAdmin"
SCHEDULER = "Scheduler"
TECHNOLOGIST = "Technologist"
QUALITY_REVIEWER = "QualityReviewer"
INTERPRETING_PHYSICIAN = "InterpretingPhysician"
PATIENT_PORTAL_USER = "PatientPortalUser"

ALL_ROLES = (
    PROGRAM_ADMIN,
    SCHEDULER,
    TECHNOLOGIST,
    QUALITY_REVIEWER,
    INTERPRETING_PHYSICIAN,
    PATIENT_PORTAL_USER,
)


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES or role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.role = role


def endpoint(*allowed_roles):
    """Wrap a view so headers and role admission are checked first."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate(allowed_roles)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def actor_id():
    return g.user_id


def actor_role():
    return g.role


def is_portal():
    return g.role == PATIENT_PORTAL_USER


def enforce_patient_scope(patient_id):
    """Ladder 17: a portal user may only address its own patient row."""
    if is_portal() and g.user_id != patient_id:
        raise ApiError("ERR_PATIENT_SCOPE_VIOLATION")
