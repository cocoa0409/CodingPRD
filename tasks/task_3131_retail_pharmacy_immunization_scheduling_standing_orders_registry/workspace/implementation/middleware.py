"""Auth header extraction and role authorization (PRD 2.1)."""
from flask import request

from errors import err

ROLES = {
    "StoreManager",
    "Pharmacist",
    "PharmacyTechnician",
    "Immunizer",
    "ObservationMonitor",
    "ComplianceOfficer",
    "Patient",
}


def require_roles(allowed):
    """Validate X-User-ID / X-User-Role headers, then role membership.

    Returns (user_id, role) on success; raises ApiError otherwise.
    Priority 1: missing/invalid headers -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    Priority 2: role not permitted      -> ERR_INSUFFICIENT_PERMISSIONS
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID or X-User-Role header missing or role unrecognized")
    if allowed is not None and role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role not permitted for this endpoint")
    return user_id, role
