# Auth middleware (PRD 2.1, validation tiers 1-2):
#   tier 1: X-User-ID and X-User-Role present and role recognized -> 401
#   tier 2: role admitted by the endpoint -> 403
from flask import request

import constants
from errors import err


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in constants.ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized authentication headers")
    return user_id, role


def authorize(role, allowed_roles):
    """Raise ERR_UNAUTHORIZED unless the role is admitted by the endpoint."""
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role %s is not permitted on this endpoint" % role)
