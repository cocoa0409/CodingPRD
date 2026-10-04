"""Authentication and role authorization (PRD §2.1, validation priorities
1 and 2). Header names are X-User-ID and X-User-Role per SCAFFOLD §1.4."""
from flask import request

from constants import ALL_ROLES
from errors import (
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
    raise_err,
)


def authenticate():
    """Priority 1: both headers present and the role is a declared role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2: the caller's role must be admitted by the endpoint."""
    if role not in allowed_roles:
        raise_err(ERR_UNAUTHORIZED_ROLE, "role %s is not authorized for this endpoint" % role)


def auth(allowed_roles):
    """Authenticate then authorize; returns (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role
