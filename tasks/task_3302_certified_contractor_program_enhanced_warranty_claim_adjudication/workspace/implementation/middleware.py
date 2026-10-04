"""Auth header extraction and role checking."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

KNOWN_ROLES = {"ProgramAdmin", "Contractor", "Distributor", "Claimant", "Inspector"}
ENTITY_BACKED = {"Contractor", "Distributor"}


def current_caller():
    """Return (user_id, role). Raises 401 if headers missing/unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None or role not in KNOWN_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or unknown X-User-Role")
    if user_id is None or user_id == "":
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID")
    return user_id, role


def require_roles(*roles):
    """Authenticate and check role membership. Returns (user_id, role)."""
    user_id, role = current_caller()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")
    return user_id, role
