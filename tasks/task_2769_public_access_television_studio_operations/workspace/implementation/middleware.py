"""Authentication and role authorisation (PRD 2.1, refusal priorities 1 and 2)."""

from flask import request

import constants
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def acting():
    """The acting (user id, role) pair, without enforcing anything."""
    role = _header(USER_ROLE_HEADER)
    if role is None:
        # Some clients spell the role header without the "User" infix.
        role = _header("X-Role")
    return _header(USER_ID_HEADER), role


def authorize(*allowed_roles):
    """Priority 1 then priority 2: 401 before 403, both before any payload work."""
    user_id, role = acting()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation" % role)
    return user_id, role


def authorize_clock():
    """The logical-clock control operation needs no headers (PRD 2.1)."""
    user_id, role = acting()
    if role is not None and role not in constants.ALL_ROLES:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation" % role)
    return user_id, role


def require_owner(actual_producer_id, user_id, role):
    """Priority 6. Ownership constrains only the Producer role (PRD 2.1)."""
    if role != constants.ROLE_PRODUCER:
        return
    if actual_producer_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting producer does not own this resource")
