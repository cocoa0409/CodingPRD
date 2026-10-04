"""Auth stages 1-2 of the validation pipeline (PRD 2.8)."""
from flask import request

import constants
from errors import err


def require_auth():
    """Stage 1: X-User-ID and X-User-Role present, role one of the six declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in constants.ALL_ROLES:
        err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must be one of the six declared roles.",
        )
    return {"user_id": user_id, "role": role}


def require_role(caller, allowed_roles):
    """Stage 2: the role must be listed for the endpoint."""
    if caller["role"] not in allowed_roles:
        err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role %s is not authorized for this operation." % caller["role"],
        )
