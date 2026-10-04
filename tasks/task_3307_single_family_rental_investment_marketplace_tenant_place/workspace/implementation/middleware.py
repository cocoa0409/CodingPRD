"""Auth middleware: header validation and RBAC role checks (validation priorities 1-2)."""
from flask import request

import errors

ROLES = {
    "PlatformAdmin",
    "Seller",
    "Buyer",
    "CertificationReviewer",
    "EscrowOfficer",
    "PropertyManager",
    "ClaimsAdjuster",
}

# Entity-backed roles: X-User-ID must be the id of a persisted entity of that type.
ENTITY_BACKED = {"Seller", "Buyer", "PropertyManager"}


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def __repr__(self):
        return f"Ctx({self.role}:{self.user_id})"


def get_ctx():
    """Priority 1: headers present, non-empty, role declared in the RBAC matrix."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not str(uid).strip() or not str(role).strip():
        raise errors.missing_headers()
    if role not in ROLES:
        raise errors.missing_headers()
    return Ctx(str(uid), role)


def require_role(ctx, *roles):
    """Priority 2 (role part): caller's role must be among the permitted roles."""
    if ctx.role not in roles:
        raise errors.forbidden()


def require_owner(ctx, owner_id):
    """Priority 2 (ownership part): entity-backed caller must own the resource."""
    if ctx.user_id != owner_id:
        raise errors.forbidden()
