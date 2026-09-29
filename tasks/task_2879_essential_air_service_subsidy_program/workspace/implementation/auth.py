"""Authentication, endpoint authorisation and resource ownership (PRD 2.1, 2.6)."""

from functools import wraps

from flask import g, request

import errors

PROGRAM_ADMIN = "ProgramAdmin"
ELIGIBILITY_ANALYST = "EligibilityAnalyst"
SELECTION_OFFICER = "SelectionOfficer"
COMMUNITY_REPRESENTATIVE = "CommunityRepresentative"
CARRIER = "Carrier"

ROLES = (
    PROGRAM_ADMIN,
    ELIGIBILITY_ANALYST,
    SELECTION_OFFICER,
    COMMUNITY_REPRESENTATIVE,
    CARRIER,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    raw_id = request.headers.get(USER_ID_HEADER)
    raw_role = request.headers.get(USER_ROLE_HEADER)
    if raw_id is None or raw_id.strip() == "":
        errors.fail(errors.ERR_UNAUTHENTICATED, "X-User-ID header is missing or empty.")
    if raw_role is None or raw_role.strip() == "":
        errors.fail(errors.ERR_UNAUTHENTICATED, "X-User-Role header is missing or empty.")
    role = raw_role.strip()
    if role not in ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED, "X-User-Role does not name a known role.")
    g.user_id = raw_id.strip()
    g.role = role


def authorize(allowed_roles):
    if g.role not in allowed_roles:
        errors.fail(errors.ERR_UNAUTHORIZED,
                    "Role %s may not call this endpoint." % g.role)


def endpoint(*allowed_roles):
    """Rungs 1 and 2 of the validation ladder, applied before anything else."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(allowed_roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def user_id():
    return g.user_id


def role():
    return g.role


def require_owner(owner_id):
    """Rung 5: an entity-backed role may only act on its own rows."""
    if g.user_id != owner_id:
        errors.fail(errors.ERR_FORBIDDEN_RESOURCE_OWNER,
                    "The acting user does not own this resource.")
