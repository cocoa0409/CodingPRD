"""Auth middleware: X-User-ID / X-User-Role header extraction and role checking."""
from __future__ import annotations

from flask import request

from errors import err_forbidden_role, err_missing_context

ROLES = {
    "LicensingAdmin",
    "RightsOfficer",
    "RosterOperator",
    "RosterReviewer",
    "LiveOpsManager",
    "FinanceController",
    "LeagueAuditor",
    "UnionAuditor",
    "ComplianceReviewer",
}


def get_auth():
    """Return (user_id, role) or raise ERR_MISSING_CONTEXT."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or uid.strip() == "":
        raise err_missing_context()
    if not role or not isinstance(role, str) or role.strip() == "":
        raise err_missing_context()
    return uid, role


def require_roles(*allowed: str):
    """Check auth headers present; then role is one of the allowed set."""
    uid, role = get_auth()
    if role not in ROLES:
        # Unknown role value -> not permitted for any endpoint
        raise err_forbidden_role(f"Role {role} is not recognized")
    if role not in allowed:
        raise err_forbidden_role(f"Role {role} not permitted for this endpoint")
    return uid, role
