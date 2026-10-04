"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.7)."""

from flask import request

from errors import bad_context, forbidden_role

DECLARED_ROLES = {
    "PlatformAdmin",
    "HRRecruiter",
    "CorporateController",
    "OperationsAuditor",
    "ManagingPartner",
    "MarketPartner",
}

ALL_ROLES = (
    "PlatformAdmin",
    "HRRecruiter",
    "CorporateController",
    "OperationsAuditor",
    "ManagingPartner",
    "MarketPartner",
)

ENTITY_BACKED_ROLES = {"ManagingPartner", "MarketPartner"}


def caller():
    """Return (user_id, role). Tier-1 auth: both headers present, non-empty, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise bad_context()
    if role not in DECLARED_ROLES:
        raise bad_context("X-User-Role names an undeclared role")
    return user_id, role


def require_roles(*roles):
    """Auth (tier 1) + authorization (tier 2). Returns (user_id, role)."""
    user_id, role = caller()
    if role not in roles:
        raise forbidden_role("Role %s not permitted for this endpoint" % role)
    return user_id, role
