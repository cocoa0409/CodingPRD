"""Auth header extraction and role gating (PRD 2.1, validations 1, 2 and 6)."""
from flask import g, request

from errors import ApiError

ROLE_ADMIN = "StoreOperationsAdmin"
ROLE_MANAGER = "DepartmentManager"
ROLE_CLERK = "FreshClerk"
ROLE_AUDITOR = "ComplianceAuditor"
ROLE_PARTNER = "DonationPartner"

ALL_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_CLERK, ROLE_AUDITOR, ROLE_PARTNER)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate(*allowed_roles):
    """Validation priority 1 (401) then priority 2 (403)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required",
        )
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Unknown role %s" % role)
    if allowed_roles and role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s may not call this endpoint" % role,
        )
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def actor():
    return g.get("user_id")


def role():
    return g.get("user_role")


def is_partner():
    return g.get("user_role") == ROLE_PARTNER


def require_pickup_ownership(pickup):
    """Validation priority 6: entity-backed DonationPartner identity."""
    if is_partner() and pickup.get("partner_id") != actor():
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "This pickup belongs to another food-bank partner",
        )
