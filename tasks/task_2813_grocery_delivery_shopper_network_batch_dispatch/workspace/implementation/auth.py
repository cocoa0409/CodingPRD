"""Authentication, role authorization and ownership checks (PRD 2.1, 2.8)."""
from flask import g, request

from errors import fail

ROLES = ("Customer", "Shopper", "RetailerManager", "DispatchAdmin", "CustomerSupport")
OPAQUE_ROLES = ("DispatchAdmin", "CustomerSupport")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Rank 1 then rank 2 of the rejection ladder."""
    authenticate()
    if g.role not in roles:
        fail("ERR_UNAUTHORIZED_ROLE")


def require_owner(expected_id):
    """Rank 4: entity-backed roles must own the addressed resource.

    DispatchAdmin and CustomerSupport carry opaque identifiers and can never
    fail an ownership check (PRD 2.1).
    """
    if g.role in OPAQUE_ROLES:
        return
    if expected_id is None or g.user_id != expected_id:
        fail("ERR_NOT_RESOURCE_OWNER")
