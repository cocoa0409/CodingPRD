"""Ladder steps 1-2 — authentication and role authorization (PRD 2.1)."""
from functools import wraps

from flask import g, request

from errors import ApiError
from store import db

RECEIVING_TECH = "ReceivingTech"
INVENTORY_LEAD = "InventoryLead"
CIRC_CLINICIAN = "CircClinician"
COMPLIANCE_OFFICER = "ComplianceOfficer"
REVENUE_ANALYST = "RevenueIntegrityAnalyst"
VENDOR_REP = "VendorRep"

ALL_ROLES = [
    RECEIVING_TECH,
    INVENTORY_LEAD,
    CIRC_CLINICIAN,
    COMPLIANCE_OFFICER,
    REVENUE_ANALYST,
    VENDOR_REP,
]

# The five roles that may read a surgical case / implant record (no VendorRep).
CLINICAL_READERS = [
    RECEIVING_TECH,
    INVENTORY_LEAD,
    CIRC_CLINICIAN,
    COMPLIANCE_OFFICER,
    REVENUE_ANALYST,
]


def authenticate():
    """Step 1: both headers present and non-blank; role declared; VendorRep resolves."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    if role == VENDOR_REP and user_id not in db.vendors:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID must be an existing vendor id.")
    g.user_id = user_id
    g.role = role


def authorize(roles):
    """Step 2: the acting role appears in the endpoint's authorized-roles list."""
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not call this endpoint." % g.role)


def endpoint(roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


def actor_role():
    return g.role
