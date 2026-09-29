"""Header-based authentication and RBAC (PRD 2.1, ladder rules 1-3)."""

import functools

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

BUREAU_ADMIN = "BureauAdmin"
SALES_MANAGER = "SalesManager"
HOTEL_PARTNER = "HotelPartner"
CENTER_SCHEDULER = "CenterScheduler"
MEETING_PLANNER = "MeetingPlanner"
INCENTIVE_APPROVER = "IncentiveApprover"
SERVICES_MANAGER = "ServicesManager"
BOARD_ANALYST = "BoardAnalyst"

ROLES = (
    BUREAU_ADMIN,
    SALES_MANAGER,
    HOTEL_PARTNER,
    CENTER_SCHEDULER,
    MEETING_PLANNER,
    INCENTIVE_APPROVER,
    SERVICES_MANAGER,
    BOARD_ANALYST,
)


def authenticate():
    """Rule 1: both headers present, non-empty, and a declared role name."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role must be non-empty.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a declared role.")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(*roles):
    """Bind an endpoint to its authorized roles (rule 1 then rule 2)."""

    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role %s is not authorized for this operation." % g.role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def caller_id():
    return g.user_id


def caller_role():
    return g.role


def require_owner(actual_owner_id, message):
    """Rule 3: entity-backed ownership of the target resource."""
    if caller_id() != actual_owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", message)
