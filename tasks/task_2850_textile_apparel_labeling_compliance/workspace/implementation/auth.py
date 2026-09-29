"""Authentication, role authorization and BrandAdmin scope (PRD 2.1, ladder 1/2/4)."""
from flask import g, request

from errors import fail
from store import db

ROLES = ("ComplianceAdmin", "BrandAdmin", "LabelingSpecialist", "LabelingApprover",
         "AccreditedLab", "CustomsOfficer", "Auditor")


def authenticate():
    """Ladder step 1: the very first check the service performs."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def require_roles(*allowed):
    """Ladder step 2: role authorization against the endpoint's role list."""
    authenticate()
    if g.role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not invoke this endpoint." % g.role)
    return g.user_id, g.role


def acting_role():
    return getattr(g, "role", None)


def acting_user():
    return getattr(g, "user_id", None)


def scope_brand(brand_id):
    """Ladder step 4: BrandAdmin brand-chain scope check."""
    if acting_role() != "BrandAdmin":
        return
    if brand_id is None or str(brand_id) != acting_user():
        fail("ERR_BRAND_SCOPE_VIOLATION",
             "The acting brand may only act on its own resources.")


def scope_style(style):
    scope_brand(style.get("brand_id") if style else None)


def scope_style_id(style_id):
    if acting_role() != "BrandAdmin":
        return
    style = db.styles.get(style_id) if style_id is not None else None
    scope_brand(style.get("brand_id") if style else None)
