"""Auth header extraction and role gating per PRD §2.1 (validation priorities 1-2)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = {
    'PlatformAdmin',
    'TechnicalServiceEngineer',
    'ProjectEngineer',
    'OwnerRepresentative',
    'ApplicatorRep',
    'Inspector',
    'ComplianceOfficer',
}

ALL_ROLES = (
    'PlatformAdmin', 'TechnicalServiceEngineer', 'ProjectEngineer',
    'OwnerRepresentative', 'ApplicatorRep', 'Inspector', 'ComplianceOfficer',
)


def require_roles(*allowed):
    """Reject malformed/missing headers (400) then unauthorized roles (403)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get('X-User-ID')
            role = request.headers.get('X-User-Role')
            if not uid or not uid.strip() or not role or role not in ROLES:
                raise ApiError(
                    'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', 400,
                    'X-User-ID and X-User-Role headers must be present and well-formed')
            if role not in allowed:
                raise ApiError(
                    'ERR_INSUFFICIENT_PERMISSIONS', 403,
                    'role %s is not permitted to invoke this endpoint' % role)
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
