"""Auth middleware: X-User-ID + X-User-Role validation and role gating."""
from flask import request

from errors import err_missing_ctx, err_forbidden_role

VALID_ROLES = {
    "CampaignOwner", "Backer", "FactoryCoordinator", "FreightBroker",
    "CustomsAgent", "FulfillmentOperator", "Distributor",
    "LocalizationPartner", "PlatformAdmin",
}


def require_auth(allowed_roles):
    """Return (user_id, role) or raise. allowed_roles: set of role names."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err_missing_ctx()
    if not role or role not in VALID_ROLES:
        raise err_missing_ctx()
    if role not in allowed_roles:
        raise err_forbidden_role()
    return user_id, role


ANY_ROLE = set(VALID_ROLES)
