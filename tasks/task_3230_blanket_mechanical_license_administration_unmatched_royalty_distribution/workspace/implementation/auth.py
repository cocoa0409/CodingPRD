"""Auth middleware: X-User-ID / X-User-Role, role authorization."""
from functools import wraps

from flask import request

from errors import ApiError

ROLES = {"MLCAdministrator", "ServiceProviderUser", "MemberUser", "PublicSearcher"}


def get_identity():
    """Extract (user_id, role); raise ERR_MISSING_AUTH on missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_MISSING_AUTH", "X-User-ID and X-User-Role headers are required", 401)
    if role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH", "X-User-Role is not a recognized role", 401)
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate, then authorize role membership."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED_ROLE", "Role not permitted for this endpoint", 403)
            return fn(*args, _user_id=user_id, _role=role, **kwargs)
        return wrapper
    return decorator
