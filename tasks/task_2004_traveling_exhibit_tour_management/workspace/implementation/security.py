"""Authentication and role authorization — PRD §2.1.

Every request must carry X-User-ID and X-User-Role. The five recognized
roles are TourManager, VenueRegistrar, Registrar, Shipper, Insurer. Missing
headers or an unrecognized role -> ERR_UNAUTHENTICATED (401); an identified
caller attempting another role's operation -> ERR_UNAUTHORIZED (403).
Identity is opaque: X-User-ID is never compared to any resource id.
"""

from flask import g, request

from errors import fail

ROLES = {"TourManager", "VenueRegistrar", "Registrar", "Shipper", "Insurer"}

ALL_ROLES = ("TourManager", "VenueRegistrar", "Registrar", "Shipper", "Insurer")


def authenticate():
    """Runs before every request (PRD §2.8: authentication fires first)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED",
             "Missing or unrecognized X-User-Role / X-User-ID headers")
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    if g.role not in roles:
        fail("ERR_UNAUTHORIZED", "Role not permitted for this endpoint")
