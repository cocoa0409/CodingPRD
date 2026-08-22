"""Ladder rungs 1-2: authentication and role admission (PRD §2.1, §2.6)."""
from flask import g, request

from constants import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE
from errors import fail


def authenticate():
    """Rung 1. Both headers present, non-empty, role declared."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must be non-empty.")
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "Unrecognised X-User-Role.")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*roles):
    """Rungs 1 then 2. Returns the acting user id."""
    user_id, role = authenticate()
    if role not in roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return user_id


def actor():
    return g.get("user_id")
