"""Authentication, role admission and ownership (PRD §2.1)."""

from flask import request

import store
from constants import ROLES
from errors import ApiError

ENTITY_BACKED = {
    "Applicant": "provider",
    "LicensingInspector": "inspector",
    "ComplaintInvestigator": "inspector",
}


def authenticate(allowed_roles, require_user_id=True, resolve_identity=True):
    """Returns (user_id, role) after the four authentication checks of §2.7."""
    user_id = request.headers.get("X-User-ID")
    if require_user_id and (user_id is None or user_id.strip() == ""):
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is missing or blank.")

    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is missing or unrecognised.")

    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role
        )

    if resolve_identity and role in ENTITY_BACKED:
        backing = ENTITY_BACKED[role]
        if backing == "provider" and user_id not in store.providers:
            raise ApiError(
                "ERR_UNAUTHENTICATED", "X-User-ID does not resolve to a provider."
            )
        if backing == "inspector" and user_id not in store.inspectors:
            raise ApiError(
                "ERR_UNAUTHENTICATED", "X-User-ID does not resolve to an inspector."
            )
    return user_id, role


def require_provider_owner(role, user_id, provider_id):
    """Applicant ownership over a provider-scoped resource."""
    if role == "Applicant" and user_id != provider_id:
        raise ApiError(
            "ERR_OWNERSHIP_VIOLATION", "The acting applicant does not own this resource."
        )


def require_inspection_owner(role, user_id, inspection):
    if role == "LicensingInspector" and user_id != inspection["inspector_id"]:
        raise ApiError(
            "ERR_OWNERSHIP_VIOLATION",
            "The acting inspector is not assigned to this inspection.",
        )


def require_complaint_owner(role, user_id, complaint):
    if role == "ComplaintInvestigator" and user_id != complaint.get(
        "assigned_investigator_id"
    ):
        raise ApiError(
            "ERR_OWNERSHIP_VIOLATION",
            "The acting investigator is not assigned to this complaint.",
        )
