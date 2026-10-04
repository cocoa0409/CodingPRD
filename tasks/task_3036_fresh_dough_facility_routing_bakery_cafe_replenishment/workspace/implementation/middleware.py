"""Authentication, role authorisation and CafeManager ownership (PRD 2.1)."""

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_FACILITY_PLANNER = "FacilityPlanner"
ROLE_ROUTE_DISPATCHER = "RouteDispatcher"
ROLE_CAFE_MANAGER = "CafeManager"
ROLE_DONATION_COORDINATOR = "DonationCoordinator"
ROLE_FINANCE_ADMIN = "FinanceAdmin"

ROLES = (
    ROLE_FACILITY_PLANNER,
    ROLE_ROUTE_DISPATCHER,
    ROLE_CAFE_MANAGER,
    ROLE_DONATION_COORDINATOR,
    ROLE_FINANCE_ADMIN,
)

ALL_ROLES = ROLES


def authenticate():
    """Priority 1: identity headers present and the role is declared."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if role is None or str(role).strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "The %s header is missing or names an unrecognized role." % USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "The %s header is missing or empty." % USER_ID_HEADER)
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed_roles):
    """Priorities 1 and 2 together; returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Role %s may not perform this operation." % role)
    return user_id, role


def require_cafe_owner(cafe_id):
    """CafeManager (entity_backed) may only touch resources of its own cafe."""
    if g.get("role") == ROLE_CAFE_MANAGER and g.get("user_id") != cafe_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "A cafe manager may only operate on its own cafe.")


def caller():
    return g.get("user_id"), g.get("role")
