"""Auth: X-User-ID / X-User-Role headers and role authorization."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "ProcurementOfficer",
    "ImplementationManager",
    "AgencyProjectManager",
    "VendorProjectManager",
    "FinanceOfficer",
    "BusinessAnalyst",
    "DataMigrationLead",
    "InterfaceEngineer",
    "SupportManager",
}


def require_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED, "missing or invalid X-User-ID / X-User-Role")
    return user_id, role


def require_roles(*allowed):
    user_id, role = require_auth()
    if role not in allowed:
        raise_error(ERR_FORBIDDEN, "role not permitted for this endpoint")
    return user_id, role
