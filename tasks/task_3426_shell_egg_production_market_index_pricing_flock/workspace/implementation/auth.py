"""Authentication / authorization middleware (PRD §2.1, scaffold validations
priorities 1-3).

Every request carries X-User-ID and X-User-Role. Nine declared roles. Customer
and ComplexManager are entity-backed: their X-User-ID must equal the owning
entity's id on the ownership-checked endpoints.
"""

from flask import request

from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED
from util import ROLES

_ROLE_SET = set(ROLES)


def authenticate():
    """Priority 1: both headers present and the role is one of the nine."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in _ROLE_SET:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "missing X-User-ID / X-User-Role headers or unrecognized role",
        )
    return uid, role


def require_role(role, allowed):
    """Priority 2: the role must be listed among the endpoint's roles."""
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN, 403, "role %s is not authorized for this endpoint" % role
        )


def check_customer_ownership(uid, role, customer_id):
    """Priority 3: Customer may act only on resources of its own commitments."""
    if role == "Customer" and uid != customer_id:
        raise ApiError(
            ERR_FORBIDDEN, 403, "customer may only access its own resources"
        )


def check_complex_manager_ownership(uid, role, complex_id):
    """Priority 3: ComplexManager's X-User-ID must equal the path complex id."""
    if role == "ComplexManager" and uid != complex_id:
        raise ApiError(
            ERR_FORBIDDEN, 403, "complex manager may only manage its own complex"
        )
