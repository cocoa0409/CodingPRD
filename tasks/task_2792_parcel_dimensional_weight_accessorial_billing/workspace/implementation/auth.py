"""Authentication, RBAC and shipper scoping (PRD 2.1).

Order of the four checks is fixed and the first failure wins:
header presence -> role recognition -> endpoint permission -> shipper scoping.
"""

import functools

from flask import g, request

from errors import ApiError

ROLE_CARRIER_ADMIN = "CarrierAdmin"
ROLE_CARRIER_OPS = "CarrierOps"
ROLE_BILLING_OPS = "BillingOps"
ROLE_REVENUE_AUDITOR = "RevenueAuditor"
ROLE_SHIPPER_USER = "ShipperUser"

ALL_ROLES = (
    ROLE_CARRIER_ADMIN,
    ROLE_CARRIER_OPS,
    ROLE_BILLING_OPS,
    ROLE_REVENUE_AUDITOR,
    ROLE_SHIPPER_USER,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authorize(*allowed_roles):
    """Decorator enforcing PRD 2.1 checks 1-3 for one endpoint."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(HEADER_USER_ID)
            role = request.headers.get(HEADER_USER_ROLE)
            if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
                raise ApiError("ERR_MISSING_AUTH_HEADERS",
                               "X-User-ID and X-User-Role headers are both required.")
            if role not in ALL_ROLES:
                raise ApiError("ERR_UNKNOWN_ROLE",
                               "X-User-Role must name one of the five declared roles.")
            if role not in allowed_roles:
                raise ApiError("ERR_ROLE_NOT_PERMITTED",
                               "Role %s is not authorized for this operation." % role)
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def is_shipper_user():
    return getattr(g, "role", None) == ROLE_SHIPPER_USER


def caller_id():
    return getattr(g, "user_id", None)


def enforce_shipper_scope(owning_shipper_id):
    """PRD 2.1 check 4: a ShipperUser may only reach its own account's data."""
    if is_shipper_user() and owning_shipper_id != caller_id():
        raise ApiError("ERR_SHIPPER_SCOPE_VIOLATION",
                       "A ShipperUser may only access resources of its own shipper account.")


def enforce_named_shipper(shipper_id):
    """PRD 2.1: any shipper_id a ShipperUser names must equal its own X-User-ID.

    This is a pure comparison, so it runs before existence resolution.
    """
    if shipper_id is None:
        return
    if is_shipper_user() and shipper_id != caller_id():
        raise ApiError("ERR_SHIPPER_SCOPE_VIOLATION",
                       "A ShipperUser may only name its own shipper_id.")
