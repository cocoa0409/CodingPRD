"""Auth middleware: X-User-ID / X-User-Role headers and role checking."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"RightsManager", "AdOps", "StreamOps", "PartnerManager", "Viewer"}
ENTITY_BACKED = {"Viewer"}


def get_actor():
    """Validate auth headers; return (user_id, role). Runs before anything else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "missing or malformed auth headers")
    return user_id, role


def require_roles(allowed):
    user_id, role = get_actor()
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "role not permitted for endpoint")
    return user_id, role
