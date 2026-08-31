"""Authentication and role authorisation (PRD sections 2.1 and 2.7 steps 1-2)."""

from functools import wraps

from flask import g, request

from errors import fail

ROLES = (
    "Volunteer",
    "CrewLeader",
    "StewardshipCoordinator",
    "LandManagerOfficer",
    "SafetyOfficer",
    "GrantsAdministrator",
)

ALL_ROLES = list(ROLES)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a declared role.")
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def require(*roles):
    """Step 1 (authentication) then step 2 (role authorisation)."""
    allowed = set(roles) if roles else set(ROLES)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                fail("ERR_FORBIDDEN_ROLE", "Role %s is not authorised here." % g.role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


def role():
    return g.role
