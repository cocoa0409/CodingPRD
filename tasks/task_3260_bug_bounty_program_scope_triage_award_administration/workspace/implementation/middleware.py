"""Auth middleware (PRD §2.1): X-User-ID / X-User-Role headers, role check,
researcher entity-backed ownership."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_INVALID_REQUEST

VALID_ROLES = {"Anonymous", "Researcher", "Triager", "ProgramAdmin", "PlatformAdmin"}


def get_identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_UNAUTHENTICATED, "Missing or empty X-User-ID / X-User-Role headers")
    if role not in VALID_ROLES:
        # unknown role: cannot be in any endpoint's role list
        raise_err(ERR_FORBIDDEN, "Role not allowed for this endpoint")
    return user_id, role


def require_roles(allowed):
    user_id, role = get_identity()
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role not allowed for this endpoint")
    return user_id, role


def check_researcher_owner(user_id, role, owner_id):
    """Entity-backed ownership: Researcher may only act on own resources."""
    if role == "Researcher" and user_id != owner_id:
        raise_err(ERR_FORBIDDEN, "Researcher may only act on own resources")
