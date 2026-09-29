"""Header authentication, role authorization and MarketOperator scoping."""

from flask import request

from errors import ApiError
from store import store

ROLES = (
    "PlatformAdmin",
    "FleetPlanner",
    "FleetController",
    "RemarketingManager",
    "MarketOperator",
)

ALL_ROLES = ROLES
NON_OPERATOR_ROLES = (
    "PlatformAdmin",
    "FleetPlanner",
    "FleetController",
    "RemarketingManager",
)


def authorize(allowed_roles):
    """Runs validation ranks 1-3 and returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError(
            "ERR_MISSING_AUTH_HEADERS",
            "X-User-ID and X-User-Role headers are required and must be non-empty.",
        )
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "X-User-Role '%s' is not a recognized role." % role)
    if role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not authorized for this operation." % role,
        )
    return user_id, role


def require_scope(actor_id, market_id):
    """Validation rank 4: the acting MarketOperator owns the target market."""
    if actor_id != market_id:
        raise ApiError(
            "ERR_MARKET_SCOPE_VIOLATION",
            "The acting MarketOperator does not own the target resource's market.",
        )


def acting_market(actor_id):
    return store.markets.get(actor_id)
