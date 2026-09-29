"""Identity and role-based access control (PRD 2.1, 2.12 steps 1-2)."""
from flask import request, g

import db
from errors import ApiError

PROPERTY_ADMIN = "PropertyAdmin"
NIGHT_AUDITOR = "NightAuditor"
FRONT_DESK_AGENT = "FrontDeskAgent"
OUTLET_MANAGER = "OutletManager"
REVENUE_MANAGER = "RevenueManager"
CONTROLLER = "Controller"

ALL_ROLES = (
    PROPERTY_ADMIN,
    NIGHT_AUDITOR,
    FRONT_DESK_AGENT,
    OUTLET_MANAGER,
    REVENUE_MANAGER,
    CONTROLLER,
)


def authenticate(allowed_roles):
    """Resolve the caller, then check the endpoint's role list.

    Step 1 of the rejection order: a missing, empty or unknown identity is
    ERR_UNAUTHENTICATED. Step 2: a known role that the endpoint does not admit
    is ERR_UNAUTHORIZED, and an OutletManager whose X-User-ID is not an
    existing Outlet is ERR_UNAUTHORIZED as well.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    role = role.strip()
    user_id = user_id.strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role
        )
    if role == OUTLET_MANAGER and user_id not in db.store.outlets:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "X-User-ID does not identify an existing outlet.",
        )
    g.user_id = user_id
    g.role = role
    return user_id, role
