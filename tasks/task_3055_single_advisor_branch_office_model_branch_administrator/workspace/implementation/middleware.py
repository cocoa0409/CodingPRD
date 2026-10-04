"""Auth header extraction and role checking (scaffold §1.4 priority 1-2, PRD §2.1)."""
from flask import request
from errors import err

VALID_ROLES = {"HomeOfficeAdmin", "Advisor", "BranchAdministrator", "CompliancePrincipal"}


def auth_context():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers.")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this endpoint.")
