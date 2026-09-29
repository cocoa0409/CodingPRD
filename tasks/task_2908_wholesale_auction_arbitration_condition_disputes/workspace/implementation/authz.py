"""Header-based authentication and role authorisation (PRD 2.1, precedence 1-3)."""
from flask import request

from errors import fail
from store import ROLES

ALL_ROLES = list(ROLES)


def authenticate(allowed_roles):
    """Check 1: X-User-Role present. Check 2: X-User-ID present. Check 3: role authorised.

    The role header is inspected before the identity header, so a request missing
    both is reported against the role header.
    """
    role = request.headers.get("X-User-Role")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or blank.")
    user_id = request.headers.get("X-User-ID")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or blank.")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s is not authorised for this operation." % role)
    return role, user_id
