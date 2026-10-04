"""Auth middleware: X-User-Role / X-User-ID extraction and role gating.

Validation priority 1 (auth -> ERR_UNAUTHENTICATED 401) and priority 2
(authorization -> ERR_UNAUTHORIZED 403) are enforced here. Each route calls
require_roles(...) after Flask dispatch; ownership checks for the entity-backed
Patron role are done in the route handlers.
"""
from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, raise_err

DECLARED_ROLES = {
    "Anonymous",
    "Admin",
    "Patron",
    "AccessibilityOfficer",
    "LibraryAdmin",
    "ScanOperator",
    "CrawlOperator",
    "LegalReviewer",
    "FinanceAdmin",
}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED per priority 1."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in DECLARED_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role header")
    if role == "Anonymous":
        # Anonymous carries no X-User-ID.
        return None, role
    if user_id is None or user_id == "":
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID header")
    return user_id, role


def require_roles(*roles):
    """Enforce priorities 1 and 2 for an endpoint. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in roles:
        raise_err(ERR_UNAUTHORIZED, "Role not permitted for this endpoint")
    return user_id, role
