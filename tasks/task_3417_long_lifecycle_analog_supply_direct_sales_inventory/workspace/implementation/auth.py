# Auth: X-User-ID / X-User-Role headers (PRD 2.1), priority rows 1-2.
from flask import request

import constants as C
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED


def principal():
    """Priority 1: both headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in C.ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "X-User-ID and X-User-Role headers are required and the role must be recognized")
    return uid, role


def require_roles(*roles):
    """Priority 2 (first half): the role is permitted on the endpoint."""
    uid, role = principal()
    if role not in roles:
        raise ApiError(ERR_UNAUTHORIZED, 403, "Role %s is not permitted on this endpoint" % role)
    return uid, role


def require_customer_owns(owner_customer_id, uid, role):
    """Priority 2 (second half): entity-backed Customer role may act only on
    resources whose owning customer id equals X-User-ID."""
    if role == "Customer" and owner_customer_id != uid:
        raise ApiError(ERR_UNAUTHORIZED, 403, "Customer role may only act on its own resources")
