"""Auth: X-User-ID + X-User-Role extraction and role checks (PRD 2.1)."""
from flask import request

from errors import err

ROLES = {
    "AgencyContractingOfficer",
    "AgencyRateAnalyst",
    "ConcessionerRateManager",
    "ConcessionerOpsManager",
    "ConcessionerFrontDesk",
    "ConcessionerAccountant",
    "AgencyFinancialAuditor",
    "ConcessionerMaintenanceChief",
    "ConcessionerHRManager",
    "AgencyEnvironmentalInspector",
    "SystemTestHarness",
}

READ_ROLES = ROLES - {"SystemTestHarness"}


def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and valid",
        )
    return uid, role


def require_role(*allowed):
    uid, role = get_auth()
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted")
    return uid, role


def require_read_role():
    uid, role = get_auth()
    if role not in READ_ROLES:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted")
    return uid, role
