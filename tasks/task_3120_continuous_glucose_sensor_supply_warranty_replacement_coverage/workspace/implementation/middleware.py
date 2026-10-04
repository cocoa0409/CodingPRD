"""Auth middleware: header extraction + role checking."""
from flask import request

from errors import err_missing_user_context, err_insufficient_permissions

ROLES = {
    "PlatformAdmin",
    "Prescriber",
    "CoverageReviewer",
    "FulfillmentAgent",
    "BillingAgent",
    "Patient",
    "WarrantyReviewer",
    "QualityEngineer",
    "PatientSupportAgent",
}


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_roles(*allowed):
    """Validate X-User-ID / X-User-Role headers and role membership.

    Returns a Ctx on success; raises ApiError otherwise.
    `allowed` may contain "Any" to permit any authenticated role.
    """
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise err_missing_user_context()
    if role not in ROLES:
        # Unknown role is not permitted to invoke any endpoint.
        raise err_insufficient_permissions()
    if "Any" not in allowed and role not in allowed:
        raise err_insufficient_permissions()
    return Ctx(user_id=user_id, role=role)
