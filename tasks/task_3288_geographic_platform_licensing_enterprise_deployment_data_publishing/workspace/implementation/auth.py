"""Auth: header validation (priority 1) and role authorization (priority 2)."""
from flask import request

from errors import err

ROLES = {
    "PlatformAdmin",
    "LicenseAdmin",
    "DeploymentAdmin",
    "BillingAdmin",
    "ComplianceOfficer",
    "ContentModerator",
    "NamedUser",
}


def require_auth():
    """Priority 1: X-User-ID and X-User-Role present and well-formed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID header missing or malformed")
    if not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-Role header missing or malformed")
    return user_id, role


def require_role(*allowed):
    """Priority 1 + 2 combined. Returns (user_id, role)."""
    user_id, role = require_auth()
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  f"Role {role} not authorized for this endpoint")
    return user_id, role
