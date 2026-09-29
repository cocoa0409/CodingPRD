"""Authentication, endpoint authorisation and the PropertyOwner ownership check.

PRD 2.1: every request carries X-User-ID and X-User-Role. Authentication runs
first, then endpoint authorisation, and both precede every other validation.
"""

from flask import request

import store
from errors import ApiError

OWNER = "PropertyOwner"
INSPECTOR = "HousingAgencyInspector"
TECHNICIAN = "MaintenanceTechnician"
REVIEWER = "QualityAssuranceReviewer"
APPEALS = "AppealsOfficer"
ADMIN = "PlatformAdmin"

ROLES = [OWNER, INSPECTOR, TECHNICIAN, REVIEWER, APPEALS, ADMIN]
ANY_ROLE = list(ROLES)


def authenticate(allowed_roles):
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED / ERR_UNAUTHORIZED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    if user_id == "" or role == "":
        raise ApiError("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not one of the six declared roles.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s is not authorised for this endpoint." % role)
    return user_id, role


def require_owner(role, user_id, property_id):
    """PRD 2.1 ownership reachability check for a single target resource."""
    if role != OWNER:
        return
    if property_id is None or user_id != property_id:
        raise ApiError(
            "ERR_FORBIDDEN_NOT_OWNER",
            "The acting property owner is not the owner of the target resource.",
        )


# --- reachability helpers --------------------------------------------------
def property_of_inspection(inspection_id):
    row = store.inspections.get(inspection_id)
    return None if row is None else row["property_id"]


def property_of_sweep(sweep_id):
    row = store.sweeps.get(sweep_id)
    return None if row is None else row["property_id"]


def property_of_deficiency(deficiency):
    if deficiency.get("inspection_id"):
        return property_of_inspection(deficiency["inspection_id"])
    if deficiency.get("sweep_id"):
        return property_of_sweep(deficiency["sweep_id"])
    return None


def property_of_selection(selection):
    return property_of_inspection(selection["inspection_id"])


def property_of_work_order(work_order):
    return property_of_sweep(work_order["sweep_id"])


def property_of_appeal(appeal):
    return property_of_inspection(appeal["inspection_id"])


def property_of_plan(plan):
    return property_of_inspection(plan["inspection_id"])
