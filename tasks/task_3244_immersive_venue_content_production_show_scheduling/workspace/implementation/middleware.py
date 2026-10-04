"""Auth middleware: X-User-ID + X-User-Role extraction and role checking."""

from flask import request

from errors import unauthenticated, forbidden

VALID_ROLES = {
    "ProductionDirector",
    "ContentProducer",
    "VenueScheduler",
    "VenueOpsEngineer",
    "SponsorshipManager",
    "BoxOfficeAgent",
    "Guest",
}


def require_role(*allowed):
    """Validate headers and that the role is in allowed set. Returns role string."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in VALID_ROLES or not uid:
        raise unauthenticated()
    if allowed and role not in allowed:
        raise forbidden()
    return role
