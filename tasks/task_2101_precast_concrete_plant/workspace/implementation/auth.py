"""Authentication and RBAC (PRD 2.1, order of refusal steps 1-2 and 4)."""
from flask import request

import constants
import errors


def authenticate():
    """Step 1 - both headers present and non-empty, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        errors.fail(errors.ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required.")
    return user_id, role


def require(*allowed_roles):
    """Steps 1 then 2. Returns (user_id, role).

    A role that is not listed for the endpoint - including a role name that is
    not one of the seven - fails with ERR_UNAUTHORIZED (PRD 2.1).
    """
    user_id, role = authenticate()
    if role not in allowed_roles:
        errors.fail(errors.ERR_UNAUTHORIZED,
                    "Role %s may not perform this operation." % role)
    return user_id, role


def require_any(*_ignored):
    """Every GET endpoint is available to all seven roles (PRD 2.1)."""
    return require(*constants.ALL_ROLES)
