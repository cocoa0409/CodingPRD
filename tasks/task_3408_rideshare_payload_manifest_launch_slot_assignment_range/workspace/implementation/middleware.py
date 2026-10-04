"""Auth middleware: context headers (stage 1) + role authorization (stage 2).

PRD §2.1: every request must carry X-User-ID and X-User-Role, both present
and non-empty, else ERR_MISSING_OR_INVALID_CONTEXT_HEADER (400). A role not
in the endpoint's authorized list is rejected with ERR_FORBIDDEN (403).
"""
from functools import wraps

from flask import g, request

from errors import ApiError, ERR_MISSING_OR_INVALID_CONTEXT_HEADER, forbidden

RECOGNIZED_ROLES = {
    "PlatformAdmin",
    "MissionOps",
    "ContractManager",
    "Customer",
    "IntegrationEngineer",
    "SafetyOfficer",
    "RangeOfficer",
    "Regulator",
}


def _context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip() or not role or not role.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and non-empty",
            400,
        )
    return uid, role


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = _context()
            if role not in roles:
                raise forbidden()
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
