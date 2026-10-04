from flask import request
from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"ConsortiumAdmin", "LibraryAdmin", "Patron", "SystemAnalyst"}


def actor():
    """Extract and validate the acting role/identity. Priority 1 auth check."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or unrecognized X-User-Role / X-User-ID headers")
    return role, user_id


def require_roles(allowed):
    """Priority 2: role must be in the endpoint's allowed set."""
    role, user_id = actor()
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "role not permitted on this endpoint")
    return role, user_id


def forbidden(msg="ownership check failed"):
    raise err(ERR_FORBIDDEN, msg)
