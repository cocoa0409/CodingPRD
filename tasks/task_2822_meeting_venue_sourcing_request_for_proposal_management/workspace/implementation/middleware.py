"""Auth header extraction and role gating (PRD section 2.1)."""
import functools

from flask import g, request

from errors import ApiError

ROLE_SOURCING_MANAGER = "SourcingManager"
ROLE_VENUE_REP = "VenueRep"
ROLE_CONTRACT_APPROVER = "ContractApprover"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (
    ROLE_SOURCING_MANAGER,
    ROLE_VENUE_REP,
    ROLE_CONTRACT_APPROVER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_PROGRAM_ADMIN,
)

# Every read endpoint that excludes VenueRep only.
PLANNER_SIDE = (
    ROLE_SOURCING_MANAGER,
    ROLE_CONTRACT_APPROVER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_PROGRAM_ADMIN,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authenticate(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Missing X-User-ID header")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Missing X-User-Role header")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unrecognized X-User-Role value")
    user_id = str(user_id).strip()
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s may not perform this operation" % role,
        )
    g.user_id = user_id
    g.role = role
    return user_id, role


def roles(*allowed):
    allowed_roles = tuple(allowed)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate(allowed_roles)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def own_venue(venue_id):
    """VenueRep identity is the Venue id it represents (PRD section 2.1)."""
    if g.role == ROLE_VENUE_REP and g.user_id != venue_id:
        raise ApiError(
            "ERR_VENUE_OWNERSHIP_MISMATCH",
            "Caller does not represent this venue",
        )
