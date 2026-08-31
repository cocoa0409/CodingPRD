"""Authentication and role authorisation (PRD §2.1, ladder steps 1-2)."""
from flask import request

from errors import ApiError

PROGRAM_DIRECTOR = "ProgramDirector"
SCHOOL_LIAISON = "SchoolLiaison"
SITE_COORDINATOR = "SiteCoordinator"
WAREHOUSE_LEAD = "WarehouseLead"
DONOR_RELATIONS = "DonorRelations"

ALL_ROLES = [
    PROGRAM_DIRECTOR,
    SCHOOL_LIAISON,
    SITE_COORDINATOR,
    WAREHOUSE_LEAD,
    DONOR_RELATIONS,
]
ROLE_SET = set(ALL_ROLES)


def authenticate():
    """Ladder step 1 — both headers present, role one of the five."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed):
    """Ladder step 2 — role appears in the endpoint's authorised list."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def auth(allowed):
    user_id, role = authenticate()
    authorize(role, allowed)
    return user_id, role


def school_scope(role, user_id, school_id):
    """Ladder step 6 — a SchoolLiaison acts only for its own school."""
    if role == SCHOOL_LIAISON and user_id != school_id:
        raise ApiError("ERR_SCHOOL_SCOPE_VIOLATION")


def site_scope(role, user_id, site_id):
    """Ladder step 7 — a SiteCoordinator acts only for its own site."""
    if role == SITE_COORDINATOR and user_id != site_id:
        raise ApiError("ERR_SITE_SCOPE_VIOLATION")
