"""Authentication and role/ownership helpers.

Every request must carry X-User-ID and X-User-Role. Exactly six roles are
declared. Entity-backed roles (Teacher, Donor, Vendor) compare X-User-ID to
the referenced foreign key; Anonymous, Reviewer and PlatformAdmin identities
are opaque.
"""
from flask import request

from errors import unauthenticated, forbidden

ROLES = ("Anonymous", "Teacher", "Reviewer", "Donor", "Vendor", "PlatformAdmin")


def actor():
    """Extract and validate the identity headers -> (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise forbidden("Role %s is not permitted on this endpoint" % role)
