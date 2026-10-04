"""Auth middleware: X-User-ID / X-User-Role headers; role permission checks."""
from functools import wraps

from flask import request

from errors import ApiError

ROLES = {
    "PlatformAdmin",
    "ProjectDeveloper",
    "PerformanceEngineer",
    "ServiceManager",
    "ServiceEngineer",
    "WarrantyAdmin",
    "SafetyAuthority",
    "MarketOperator",
}

ALL_ROLES = sorted(ROLES)


def current_role():
    return request.headers.get("X-User-Role")


def require_roles(allowed):
    """Decorator: enforce header presence/validity then role permission."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID and X-User-Role headers must be present and the role must be declared",
                )
            if role not in allowed:
                raise ApiError(
                    "ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role is not permitted for this endpoint",
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
