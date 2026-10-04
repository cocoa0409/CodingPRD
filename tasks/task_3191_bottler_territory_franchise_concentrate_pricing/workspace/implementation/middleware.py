from flask import request
from errors import err_unauthenticated, err_unauthorized_role

VALID_ROLES = {"PlatformAdmin", "BrandOwnerAdmin", "BottlerOps", "CustomerManager", "FieldTechnician"}


def require_roles(*roles):
    """Authenticate headers then authorize role. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in VALID_ROLES:
        raise err_unauthenticated()
    if role not in roles:
        raise err_unauthorized_role()
    return role, user_id
