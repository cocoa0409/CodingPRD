"""Auth middleware (PRD §2.1): X-User-ID + X-User-Role headers, seven roles."""

from flask import request

from errors import ApiError

ALL_ROLES = (
    "PlatformAdmin",
    "ProductLead",
    "SourcingManager",
    "ClaimsScientist",
    "MediaBuyer",
    "RetailExec",
    "LegalCounsel",
)
ROLE_SET = set(ALL_ROLES)


def require_roles(allowed):
    """Priority 1 (authn) then priority 2 (authz). Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers must be present and non-blank")
    if role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-Role names no declared role")
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "role %s is not authorized for this endpoint" % role)
    return uid, role
