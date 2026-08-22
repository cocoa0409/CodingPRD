"""Authentication and RBAC — ladder rules 1 and 2 (PRD 2.1, 2.5)."""
from flask import request

import constants
import errors


def authenticate():
    """Rule 1: both headers present and non-empty, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        errors.fail(errors.ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required.")
    return user_id, role


def require(*allowed_roles):
    """Rules 1 then 2. Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        errors.fail(errors.ERR_UNAUTHORIZED,
                    "Role %s may not perform this operation." % role)
    return user_id, role


def require_any():
    """Every read endpoint is open to all five roles (PRD 2.1)."""
    return require(*constants.ALL_ROLES)


def require_owner(actual_owner_id):
    """Rule 7: an entity-backed role may only act on a row it owns."""
    user_id, _role = authenticate()
    if user_id != actual_owner_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                    "The acting user does not own this resource.")
    return user_id
