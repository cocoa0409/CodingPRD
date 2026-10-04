"""Auth middleware per PRD §2.1 and scaffold validations priority 1-3."""

from functools import wraps

from flask import request

import errors

ROLES = {
    "PlatformAdmin",
    "RegionalManager",
    "FieldConsultant",
    "ComplianceAuditor",
    "SurveyVendor",
    "DealerPrincipal",
    "Customer",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED when missing/invalid.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Decorator factory: authenticate, then authorize role membership."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise errors.unauthorized()
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return decorator
