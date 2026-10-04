"""RBAC: X-User-ID + X-User-Role header extraction, role gating."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "DcaApplicant",
    "NrcReviewer",
    "DoeProgram",
    "UtilityParticipant",
    "SupplyChainManager",
    "VendorAuditor",
    "SitePermitApplicant",
    "PublicIntervenor",
    "WorkforceCoordinator",
}


def get_user_id():
    return request.headers.get("X-User-ID")


def get_role():
    return request.headers.get("X-User-Role")


def require_role(*allowed):
    """Check authentication and authorization. Returns (user_id, role)."""
    role = get_role()
    if not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "missing or invalid X-User-Role")
    if allowed and role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403, f"role {role} not permitted")
    return get_user_id(), role


def require_any_role():
    return require_role()
