"""Auth middleware: X-User-ID / X-User-Role extraction, RBAC enforcement."""

from flask import request

from errors import raise_err

ROLES = {
    "NetworkOperator",
    "SponsorshipManager",
    "RulesAdministrator",
    "DisputeAnalyst",
    "PricingAnalyst",
    "FraudAnalyst",
    "SettlementOperator",
    "CertificationEngineer",
    "Member",
}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED when missing/unrecognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role / X-User-ID headers")
    return user_id, role


def require_roles(allowed):
    """Validate auth headers then enforce RBAC. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_err("ERR_FORBIDDEN", "Role not permitted for this endpoint")
    return user_id, role
