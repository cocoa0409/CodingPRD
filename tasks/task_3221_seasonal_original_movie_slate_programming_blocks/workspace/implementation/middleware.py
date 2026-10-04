"""Auth middleware: X-User-Role + X-User-ID validation and role gating."""
from functools import wraps

from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

RECOGNIZED_ROLES = {
    "PlatformAdmin",
    "SlatePlanner",
    "ProductionManager",
    "TalentAgent",
    "ProgrammingExec",
    "AdSalesRep",
    "StreamingCurator",
    "LicensingManager",
}


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def require_auth(allowed_roles):
    """Decorator factory: enforces presence + recognition + endpoint role list."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = get_role()
            user_id = get_user_id()
            if not role or role not in RECOGNIZED_ROLES or not user_id:
                raise err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role / X-User-ID")
            if role not in allowed_roles:
                raise err(ERR_FORBIDDEN, f"Role {role} not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
