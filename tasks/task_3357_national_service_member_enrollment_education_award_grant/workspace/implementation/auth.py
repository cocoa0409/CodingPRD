"""Access tiers, evaluated in the PRD 2.10 fixed order:

(1) authentication  -> ERR_UNAUTHENTICATED (401)
(2) role authorization / (3) entity-backed ownership -> ERR_UNAUTHORIZED (403)
(4) org debarment -> ERR_ORG_DEBARRED (403)
"""
from flask import request

import constants as C
import db
from errors import ApiError


def authenticate():
    """Tier 1: X-User-ID and X-User-Role present; role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in C.ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return uid, role


def authorize(role, allowed_roles):
    """Tier 2: caller role is admitted by the endpoint."""
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "Caller role is not permitted on this endpoint"
        )


def check_grantee_ownership(uid, role, organization_id):
    """Tier 3 (org-scoped): GranteeStaff X-User-ID equals the resource's org id."""
    if role == "GranteeStaff" and uid != organization_id:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "Resource belongs to a different organization"
        )


def check_member_ownership(uid, role, member_id):
    """Tier 3 (member-scoped): Member X-User-ID equals the resource's member id."""
    if role == "Member" and uid != member_id:
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "Resource belongs to a different member"
        )


def check_not_debarred(uid, role):
    """Tier 4: a DEBARRED organization's staff lose write access."""
    if role == "GranteeStaff":
        org = db.store.organizations.get(uid)
        if org is not None and org["status"] == "DEBARRED":
            raise ApiError("ERR_ORG_DEBARRED", 403, "Organization is debarred")
