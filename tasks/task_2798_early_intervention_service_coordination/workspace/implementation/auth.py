"""Authentication, role permission and ownership enforcement."""
from functools import wraps

from flask import g, request

from errors import fail

ROLES = (
    "IntakeSpecialist",
    "ProgramAdmin",
    "Evaluator",
    "FiscalOfficer",
    "ServiceCoordinator",
    "Provider",
    "FamilyRepresentative",
)

STAFF_READ = (
    "ProgramAdmin",
    "ServiceCoordinator",
    "Evaluator",
    "FiscalOfficer",
    "IntakeSpecialist",
)

ENTITY_BACKED = ("ServiceCoordinator", "Provider", "FamilyRepresentative")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED",
             "X-User-ID and X-User-Role must be present and name a declared role.")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles):
    allowed = tuple(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                fail("ERR_ROLE_NOT_PERMITTED",
                     "Role %s may not use this endpoint." % g.role)
            g.touched_rows = {}
            g.created_rows = set()
            return view(*args, **kwargs)
        return wrapper
    return decorator


def require_owner(expected_id):
    """Ownership guard for entity-backed roles on write endpoints."""
    if g.role not in ENTITY_BACKED:
        return
    if expected_id is None or g.user_id != expected_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "The acting identity does not own this resource.")
